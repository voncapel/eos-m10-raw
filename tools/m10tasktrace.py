#!/usr/bin/env python3
"""Offline CH12 DMA replay and sampled-task exposure (standard library only).

CLI: --timeline M10TLF.BIN [--tasks M10TSK.BIN] [--names pointers.json]
     [--capture-ticks M10X3T.BIN] [--period-us 40000]
     [--threshold-us 22000] [--assert-no-stretch] [--json]

Exit codes: 0 successful replay; 1 suspects with --assert-no-stretch;
2 invalid input/arguments. JSON is a single object on stdout, including errors.

Reusable API: parse_timeline(bytes), parse_capture_ticks(bytes), parse_tasks(bytes),
load_names(path), replay_timeline(Timeline, period_us, threshold_us, CaptureTicks),
align_tasks(replay, TaskTrace), correlate_tasks(replay, TaskTrace, alignment, names),
and analyze_files(timeline, tasks=None, names=None, period_us=40000,
threshold_us=22000, capture_ticks=None). Paths are local files, never devices.

TSK1 v153 header is 16 little-endian uint32s. Word 6 is a recorded opaque
current_task_addr, NOT a host address to read. Word 15 is the confirmed
first_readout_elapsed_us anchor, or 0xffffffff if absent. Records are count
pairs (elapsed_us, task_ptr), not capacity pairs. Zero samples/period is a valid
OFF trace. No firmware, PTP, USB, TCB layout, or address dereference is imported.
"""

import argparse
from bisect import bisect_right
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import struct
import sys


U20 = 1 << 20
MASK20 = U20 - 1
VALID = 1 << 31
TLF_MAGIC = 0x31464C54
TASK_MAGIC = 0x314B5354
NO_ANCHOR = 0xFFFFFFFF
DEFAULT_PERIOD_US = 40000
DEFAULT_THRESHOLD_US = 22000


class FormatError(ValueError):
    """A binary file violates its explicit on-disk contract."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise FormatError(message)


@dataclass(frozen=True)
class Timeline:
    rows: tuple
    he_n: int
    errors: tuple


@dataclass(frozen=True)
class CaptureTicks:
    ticks_ms: tuple
    write_duration_us: tuple


@dataclass(frozen=True)
class TaskTrace:
    header: dict
    records: tuple


TASK_FIELDS = (
    'magic', 'header_bytes', 'record_bytes', 'count', 'capacity', 'period_us',
    'current_task_addr', 'start_u20', 'stop_u20', 'stop_elapsed_us',
    'timer_bad_count', 'timer_arm_error', 'max_callback_us', 'full', 'version',
    'first_readout_elapsed_us',
)


def _words(data, label):
    if len(data) % 4:
        raise FormatError('%s: byte size is not a multiple of four' % label)
    return struct.unpack('<%dI' % (len(data) // 4), data)


def parse_timeline(data):
    """Parse exact TLF1: 4I header, 32I error slots, n rows of 8I."""
    if len(data) < 144:
        raise FormatError('TLF1: truncated header/error slots (need 144 bytes)')
    magic, n, cols, he_n = struct.unpack_from('<4I', data)
    if magic != TLF_MAGIC:
        raise FormatError('TLF1: bad magic')
    if cols != 8:
        raise FormatError('TLF1: expected cols=8, got %d' % cols)
    if len(data) != 144 + n * 32:
        raise FormatError('TLF1: size/count mismatch (expected %d, got %d)' %
                          (144 + n * 32, len(data)))
    errors = struct.unpack_from('<32I', data, 16)
    rows = tuple(struct.iter_unpack('<8I', data[144:]))
    return Timeline(rows, he_n, errors)


def parse_capture_ticks(data):
    """Parse n, n relative capture ticks in ms, n write durations in us."""
    words = _words(data, 'M10X3T')
    if not words:
        raise FormatError('M10X3T: missing count')
    n = words[0]
    if len(words) != 1 + 2 * n:
        raise FormatError('M10X3T: size/count mismatch')
    return CaptureTicks(words[1:1 + n], words[1 + n:])


def parse_tasks(data):
    """Parse the v153 TSK1 contract; preserve opaque pointers as integers."""
    if len(data) < 64:
        raise FormatError('TSK1: truncated 64-byte header')
    h = dict(zip(TASK_FIELDS, struct.unpack_from('<16I', data)))
    if h['magic'] != TASK_MAGIC:
        raise FormatError('TSK1: bad magic')
    if (h['header_bytes'], h['record_bytes'], h['version']) != (64, 8, 153):
        raise FormatError('TSK1: unsupported header/record size or version')
    if h['count'] > h['capacity']:
        raise FormatError('TSK1: count exceeds capacity')
    if len(data) != 64 + 8 * h['count']:
        raise FormatError('TSK1: size/count mismatch (records must be count, not capacity)')
    if h['count'] and not h['period_us']:
        raise FormatError('TSK1: nonempty trace with zero sampling period')
    if h['start_u20'] >= U20 or h['stop_u20'] >= U20:
        raise FormatError('TSK1: start/stop are not low20 values')
    if h['full'] not in (0, 1):
        raise FormatError('TSK1: full must be 0 or 1')
    if (h['start_u20'] + h['stop_elapsed_us']) % U20 != h['stop_u20']:
        raise FormatError('TSK1: stop_u20 disagrees with elapsed clock')
    records = tuple(struct.iter_unpack('<2I', data[64:]))
    previous = -1
    for elapsed, pointer in records:
        if elapsed <= previous:
            raise FormatError('TSK1: sample elapsed times must be strictly increasing')
        if elapsed > h['stop_elapsed_us']:
            raise FormatError('TSK1: sample after stop_elapsed_us')
        previous = elapsed
    anchor = h['first_readout_elapsed_us']
    if anchor != NO_ANCHOR and anchor > h['stop_elapsed_us']:
        raise FormatError('TSK1: first readout anchor outside trace')
    return TaskTrace(h, records)


def load_timeline(path):
    return parse_timeline(Path(path).read_bytes())


def load_capture_ticks(path):
    return parse_capture_ticks(Path(path).read_bytes())


def load_tasks(path):
    return parse_tasks(Path(path).read_bytes())


def load_names(path):
    """Read an optional JSON object mapping hexadecimal uint32 pointers to names."""
    obj = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise FormatError('names: expected an object mapping hex pointer to name')
    names = {}
    for key, value in obj.items():
        try:
            pointer = int(key, 16)
        except (TypeError, ValueError) as exc:
            raise FormatError('names: invalid hex pointer %r' % key) from exc
        if not 0 <= pointer <= 0xFFFFFFFF or not isinstance(value, str):
            raise FormatError('names: uint32 hex keys and string names required')
        if pointer in names:
            raise FormatError('names: duplicate normalized pointer %r' % key)
        names[pointer] = value
    return names


def _stamp(value):
    return value & MASK20 if value & VALID else None


def _round_slot(value, period):
    # Integer half-up, unlike Python's ties-to-even round().
    return (2 * value + period) // (2 * period)


def _summary(values):
    if not values:
        return {'count': 0, 'min_us': None, 'median_us': None, 'max_us': None}
    return {'count': len(values), 'min_us': min(values),
            'median_us': statistics.median(values), 'max_us': max(values)}


def replay_timeline(timeline, period_us=DEFAULT_PERIOD_US,
                    threshold_us=DEFAULT_THRESHOLD_US, capture_ticks=None):
    """Unwrap observed readouts without replacing sensor gaps by row numbers.

    Without coarse ticks only the minimum nonnegative modulo20 gap is known;
    a gap of one complete timer turn or more cannot be excluded. Coarse capture
    ticks are approximate observations of the corresponding frame, not the
    first-line hardware event. They choose extra turns, not the precise phase.
    """
    if period_us <= 0 or not 0 <= threshold_us < U20:
        raise ValueError('period_us must be positive; threshold_us must be in [0, 2^20)')
    if capture_ticks is not None and len(capture_ticks.ticks_ms) < len(timeline.rows):
        raise FormatError('M10X3T: fewer capture ticks than timeline rows')
    warnings = []
    if capture_ticks is None:
        warnings.append('No coarse capture ticks: gaps >= 2^20 us may contain '
                        'unobserved whole timer turns; unwrap is a lower bound.')
    ticks_unwrapped = []
    if capture_ticks is not None:
        previous = None
        elapsed = 0
        for raw in capture_ticks.ticks_ms:
            if previous is not None:
                delta = (raw - previous) & 0xFFFFFFFF
                if delta >= 1 << 31:
                    raise FormatError('M10X3T: nonmonotonic capture ticks')
                elapsed += delta * 1000
            ticks_unwrapped.append(elapsed)
            previous = raw
    events = []
    first_raw = None
    previous_raw = None
    previous_index = None
    elapsed = 0
    gaps = []
    invalid_readouts = []
    unwrap_ambiguities = []
    for index, row in enumerate(timeline.rows):
        raw = _stamp(row[1])
        if raw is None:
            invalid_readouts.append(index)
            continue
        gap = None
        extra_turns = 0
        if first_raw is None:
            first_raw = raw
        else:
            gap = (raw - previous_raw) % U20
            if capture_ticks is not None:
                coarse_delta = ticks_unwrapped[index] - ticks_unwrapped[previous_index]
                extra_turns = max(0, _round_slot(coarse_delta - gap, U20))
                gap += extra_turns * U20
                residual = abs(coarse_delta - gap)
                if residual >= U20 // 4:
                    issue = {'row': index, 'coarse_gap_us': coarse_delta,
                             'chosen_gap_us': gap, 'residual_us': residual}
                    unwrap_ambiguities.append(issue)
                    warnings.append('Row %d: coarse capture gap is too far from the '
                                    'modulo20 readout gap; whole-turn inference is uncertain.' % index)
            if gap == 0:
                unwrap_ambiguities.append({'row': index, 'chosen_gap_us': 0,
                                           'reason': 'identical readout timestamps'})
                warnings.append('Row %d: identical readout timestamps are ambiguous.' % index)
            elapsed += gap
            gaps.append(gap)
        end = _stamp(row[2])
        duration = None if end is None else (end - raw) % U20
        suspect = duration is not None and duration > threshold_us
        slot = _round_slot(elapsed, period_us)
        event = {
            'row': index, 'readout_u20': raw, 'readout_us': elapsed,
            'sensor_slot': slot, 'phase_residual_us': elapsed - slot * period_us,
            'readout_gap_us': gap, 'extra_timer_turns': extra_turns,
            'dma_duration_us': duration,
            'classification': 'unknown' if duration is None else ('stretch' if suspect else 'normal'),
            'suspect': suspect,
        }
        # Events remain relative to their readout; DMA/encoder/SD clocks use the
        # same low20 modular arithmetic. Address columns 0/7 are never decoded.
        for label, start_col, end_col in (('encoder', 3, 4), ('sd', 5, 6)):
            start, stop = _stamp(row[start_col]), _stamp(row[end_col])
            event[label + '_start_offset_us'] = None if start is None else (start - raw) % U20
            event[label + '_duration_us'] = None if start is None or stop is None else (stop - start) % U20
        if capture_ticks is not None:
            event['capture_tick_ms'] = capture_ticks.ticks_ms[index]
            event['write_duration_us'] = capture_ticks.write_duration_us[index]
        events.append(event)
        previous_raw, previous_index = raw, index
    missing_sensor_slots = 0
    repeated_slots = []
    for previous, event in zip(events, events[1:]):
        distance = event['sensor_slot'] - previous['sensor_slot']
        missing_sensor_slots += max(0, distance - 1)
        if distance == 0:
            repeated_slots.append(event['row'])
    if invalid_readouts:
        warnings.append('Rows with invalid readout bit31 are excluded, not assigned synthetic times.')
    if any(event['dma_duration_us'] is None for event in events):
        warnings.append('Invalid DMA-end bit31: row classification is unknown, not normal.')
    if repeated_slots:
        warnings.append('Several readouts quantize to the same relative sensor slot; timestamps were not snapped.')
    if timeline.he_n > 32:
        warnings.append('TLF1 error count exceeds the 32 stored error slots; slots are truncated by firmware.')
    suspects = [event['row'] for event in events if event['suspect']]
    phase_counts = [0] * 16
    for event in events:
        if event['suspect']:
            phase_counts[event['sensor_slot'] % 16] += 1
    peak = max(phase_counts)
    phase_summary = {
        'counts': {str(phase): count for phase, count in enumerate(phase_counts)},
        'dominant_phases': [phase for phase, count in enumerate(phase_counts) if count == peak] if peak else [],
        'dominant_count': peak,
        'note': 'sensor_slot modulo 16 uses the arbitrary first-valid-readout phase origin; '
                'not row index modulo 16 and not an absolute firmware phase.',
    }
    return {
        'format': 'TLF1', 'period_us': period_us, 'threshold_us': threshold_us,
        'row_count': len(timeline.rows), 'valid_readout_count': len(events),
        'he_n': timeline.he_n,
        'errors': list(timeline.errors[:min(timeline.he_n, 32)]),
        'suspect_count': len(suspects), 'suspect_rows': suspects,
        'suspect_sensor_phase_mod16': phase_summary,
        'unknown_dma_count': sum(event['classification'] == 'unknown' for event in events),
        'first_readout_u20': first_raw,
        'phase_origin': 'The first valid readout is relative time 0 and sensor slot 0. '
                        'This phase origin is arbitrary, not Canon sensor phase or capture-start phase. '
                        'Slots are rounded relative to it; real readout timestamps/gaps are preserved.',
        'unwrap_basis': 'coarse_ms_capture_ticks' if capture_ticks is not None else 'minimum_modulo20',
        'unwrap_ambiguities': unwrap_ambiguities,
        'missing_sensor_slots_estimate': missing_sensor_slots,
        'repeated_sensor_slot_rows': repeated_slots,
        'invalid_readout_rows': invalid_readouts,
        'readout_gap_stats': _summary(gaps),
        'dma_duration_stats': _summary([event['dma_duration_us'] for event in events
                                        if event['dma_duration_us'] is not None]),
        'events': events, 'warnings': warnings,
    }


def align_tasks(replay, tasks):
    """Anchor the first valid TLF readout to elapsed task time, or report ambiguity.

    A validated word15 anchor describes TLF row0, not any later valid readout.
    Without it enumerate every congruent origin inside the trace. Duration or
    task prevalence never breaks a tie. Ambiguous traces are not correlated.
    """
    h = tasks.header
    base = {'status': 'unavailable', 'first_readout_elapsed_us': None,
            'candidate_offsets_us': [], 'source': None}
    if not replay['events']:
        return dict(base, reason='No valid readout')
    if replay['unwrap_ambiguities']:
        return dict(base, reason='Timeline whole-turn unwrapping is uncertain')
    if not tasks.records:
        return dict(base, reason='No task samples (OFF, failed start, or empty trace)')
    first = replay['events'][0]
    anchor = h['first_readout_elapsed_us']
    if anchor != NO_ANCHOR:
        if first['row'] != 0:
            return dict(base, reason='Header anchor describes invalid TLF row0; cannot validate congruence')
        if (h['start_u20'] + anchor) % U20 != first['readout_u20']:
            raise FormatError('TSK1: first readout anchor fails TLF modulo20 congruence')
        return dict(base, status='aligned', first_readout_elapsed_us=anchor,
                    candidate_offsets_us=[anchor], source='header_word15')
    residue = (first['readout_u20'] - h['start_u20']) % U20
    candidates = list(range(residue, h['stop_elapsed_us'] + 1, U20))
    if not candidates:
        return dict(base, reason='No congruent first readout within task trace', source='modulo20')
    if len(candidates) != 1:
        return dict(base, status='ambiguous', candidate_offsets_us=candidates,
                    source='modulo20', reason='Multiple whole-turn placements inside trace; '
                    'supply a validated firmware word15 anchor, do not select by task content')
    return dict(base, status='aligned', first_readout_elapsed_us=candidates[0],
                candidate_offsets_us=candidates, source='modulo20_unique')


def _task_label(pointer, names):
    return {'task_ptr': '0x%08x' % pointer, 'name': names.get(pointer)}


def _sample_intervals(tasks):
    """Zero-order hold sample state, cap each hold at 3 sampling periods."""
    stop = tasks.header['stop_elapsed_us']
    cap = tasks.header['period_us'] * 3
    intervals = []
    gaps = []
    durations = []
    if tasks.records and tasks.records[0][0] > 0:
        gaps.append({'start_us': 0, 'end_us': tasks.records[0][0], 'reason': 'before_first_sample'})
    for i, (start, pointer) in enumerate(tasks.records):
        end = tasks.records[i + 1][0] if i + 1 < len(tasks.records) else stop
        durations.append(end - start)
        trusted_end = min(end, start + cap)
        if trusted_end > start and pointer:
            intervals.append((start, trusted_end, pointer))
        elif trusted_end > start:
            gaps.append({'start_us': start, 'end_us': trusted_end, 'reason': 'null_task_pointer'})
        if end > trusted_end:
            gaps.append({'start_us': trusted_end, 'end_us': end, 'reason': 'interval_cap'})
    if not tasks.records and stop:
        gaps.append({'start_us': 0, 'end_us': stop, 'reason': 'no_samples'})
    return intervals, gaps, durations, cap


def correlate_tasks(replay, tasks, alignment, names=None):
    """Time-weighted task exposure, not task-switch reconstruction or causality.

    Each frame uses [readout, min(next readout, readout + sensor period)].
    Sensor gaps are not handed to the previous frame. No preceding sample
    means no attribution. Long missed sample intervals are capped, never
    normalized away; coverage is reported per frame and per normal/stretch class.
    """
    names = names or {}
    intervals, gaps, durations, cap = _sample_intervals(tasks)
    stats = {
        'sample_count': len(tasks.records), 'sampling_period_us': tasks.header['period_us'],
        'interval_cap_us': cap, 'interval_stats': _summary(durations),
        'over_cap_interval_count': sum(duration > cap for duration in durations),
        'gaps': gaps, 'gap_us': sum(g['end_us'] - g['start_us'] for g in gaps),
        'attributed_trace_us': sum(end - start for start, end, pointer in intervals),
        'unknown_nonirq_us': sum(g['end_us'] - g['start_us'] for g in gaps
                                if g['reason'] == 'null_task_pointer'),
        'unknown_nonirq_sample_count': sum(pointer == 0 for elapsed, pointer in tasks.records),
        'trace_duration_us': tasks.header['stop_elapsed_us'],
    }
    stats['trace_coverage'] = (stats['attributed_trace_us'] / stats['trace_duration_us']
                               if stats['trace_duration_us'] else None)
    result = {
        'status': alignment['status'], 'alignment': alignment, 'intervals': stats,
        'method': 'Time-weighted zero-order-held sampled TASK ownership, capped at '
                  '3 sampling periods. Frame windows end at min(next readout, readout + period); '
                  'the last uses one period. Pointer zero means unknown/non-IRQ context: '
                  'it contributes only to unknown_nonirq counters, never a task. Uncovered intervals are not attributed.',
        'interpretation': 'Enrichment is descriptive association, NOT causal proof. '
                          'TASK samples do not identify IRQ execution or exact task switches. '
                          'Inspect per-frame coverage and gaps before comparing frequencies.',
        'per_frame': [], 'classes': {}, 'tasks': [],
    }
    if alignment['status'] != 'aligned':
        return result
    origin = alignment['first_readout_elapsed_us']
    events = replay['events']
    sample_times = [sample[0] for sample in tasks.records]
    interval_ends = [interval[1] for interval in intervals]
    nonirq_gaps = [gap for gap in gaps if gap['reason'] == 'null_task_pointer']
    nonirq_ends = [gap['end_us'] for gap in nonirq_gaps]
    class_sums = {label: {'frame_count': 0, 'window_us': 0, 'covered_us': 0,
                           'uncovered_us': 0, 'unknown_nonirq_us': 0,
                           'unknown_nonirq_sample_count': 0, 'task_us': {}, 'sample_counts': {}}
                  for label in ('normal', 'stretch', 'unknown')}
    sensor_gap_us = 0
    for i, event in enumerate(events):
        start = origin + event['readout_us']
        next_readout = origin + events[i + 1]['readout_us'] if i + 1 < len(events) else start + replay['period_us']
        end = min(next_readout, start + replay['period_us'])
        sensor_gap_us += max(0, next_readout - end)
        weights = {}
        j = bisect_right(interval_ends, start)
        while j < len(intervals) and intervals[j][0] < end:
            left, right, pointer = intervals[j]
            overlap = max(0, min(end, right) - max(start, left))
            if overlap:
                weights[pointer] = weights.get(pointer, 0) + overlap
            j += 1
        counts = {}
        lo, hi = bisect_right(sample_times, start - 1), bisect_right(sample_times, end - 1)
        for sample_time, pointer in tasks.records[lo:hi]:
            counts[pointer] = counts.get(pointer, 0) + 1
        nonirq_us = 0
        j = bisect_right(nonirq_ends, start)
        while j < len(nonirq_gaps) and nonirq_gaps[j]['start_us'] < end:
            gap = nonirq_gaps[j]
            nonirq_us += max(0, min(end, gap['end_us']) - max(start, gap['start_us']))
            j += 1
        nonirq_count = counts.pop(0, 0)
        covered = sum(weights.values())
        window = end - start
        frame = {'row': event['row'], 'sensor_slot': event['sensor_slot'],
                 'classification': event['classification'], 'start_us': start, 'end_us': end,
                 'window_us': window, 'covered_us': covered, 'uncovered_us': window - covered,
                 'coverage': covered / window if window else None,
                 'unknown_nonirq_us': nonirq_us, 'unknown_nonirq_sample_count': nonirq_count,
                 'sample_count': sum(counts.values()),
                 'task_exposure': [dict(_task_label(p, names), exposure_us=w,
                                        covered_share=w / covered if covered else None)
                                   for p, w in sorted(weights.items())]}
        result['per_frame'].append(frame)
        bucket = class_sums[event['classification']]
        bucket['frame_count'] += 1
        for key in ('window_us', 'covered_us', 'uncovered_us',
                    'unknown_nonirq_us', 'unknown_nonirq_sample_count'):
            bucket[key] += frame[key]
        for pointer, weight in weights.items():
            bucket['task_us'][pointer] = bucket['task_us'].get(pointer, 0) + weight
        for pointer, count in counts.items():
            bucket['sample_counts'][pointer] = bucket['sample_counts'].get(pointer, 0) + count
    for label, bucket in class_sums.items():
        result['classes'][label] = {
            key: value for key, value in bucket.items() if key not in ('task_us', 'sample_counts')}
        result['classes'][label]['coverage'] = (bucket['covered_us'] / bucket['window_us']
                                               if bucket['window_us'] else None)
        result['classes'][label]['sample_count'] = sum(bucket['sample_counts'].values())
    pointers = sorted(set(p for b in class_sums.values() for p in b['task_us']) |
                      set(p for b in class_sums.values() for p in b['sample_counts']))
    for pointer in pointers:
        item = _task_label(pointer, names)
        shares = {}
        for label, bucket in class_sums.items():
            exposure = bucket['task_us'].get(pointer, 0)
            share = exposure / bucket['covered_us'] if bucket['covered_us'] else None
            shares[label] = share
            samples = bucket['sample_counts'].get(pointer, 0)
            total_samples = sum(bucket['sample_counts'].values())
            item[label] = {'exposure_us': exposure, 'covered_share': share,
                           'window_share': exposure / bucket['window_us'] if bucket['window_us'] else None,
                           'sample_count': samples,
                           'sample_share': samples / total_samples if total_samples else None}
        normal, stretch = shares['normal'], shares['stretch']
        item['stretch_enrichment'] = (stretch / normal if normal and stretch is not None else None)
        result['tasks'].append(item)
    result['sensor_gap_us_excluded'] = sensor_gap_us
    return result


def analyze_files(timeline, tasks=None, names=None, period_us=DEFAULT_PERIOD_US,
                  threshold_us=DEFAULT_THRESHOLD_US, capture_ticks=None):
    """Stable file API, returning only JSON-serializable built-in objects.

    Corresponding *_M10X3T.BIN is auto-discovered beside *_M10TLF.BIN (or
    M10TLF.BIN beside M10X3T.BIN). Explicit capture_ticks overrides discovery.
    Auto-discovered malformed files fail loudly rather than silently changing
    the time base. Timeline-only operation never needs a TSK1 file.
    """
    timeline_path = Path(timeline)
    ticks_path = Path(capture_ticks) if capture_ticks is not None else None
    if ticks_path is None and timeline_path.name.upper().endswith('M10TLF.BIN'):
        candidate = timeline_path.with_name(timeline_path.name[:-len('M10TLF.BIN')] + 'M10X3T.BIN')
        if candidate.is_file():
            ticks_path = candidate
    parsed = load_timeline(timeline_path)
    ticks = load_capture_ticks(ticks_path) if ticks_path is not None else None
    replay = replay_timeline(parsed, period_us, threshold_us, ticks)
    result = {'schema_version': 1, 'timeline_file': str(timeline_path),
              'capture_ticks_file': str(ticks_path) if ticks_path is not None else None,
              'timeline': replay, 'task_trace': None, 'correlation': None}
    if tasks is not None:
        trace = load_tasks(tasks)
        labels = load_names(names) if names is not None else {}
        result['task_trace'] = {'file': str(tasks), 'header': trace.header,
                                'warnings': []}
        if trace.header['full']:
            result['task_trace']['warnings'].append('Trace capacity reached; coverage may end before the capture.')
        if trace.header['timer_bad_count'] or trace.header['timer_arm_error']:
            result['task_trace']['warnings'].append('Timer health errors: elapsed-clock and sampling reliability need review.')
        alignment = align_tasks(replay, trace)
        result['correlation'] = correlate_tasks(replay, trace, alignment, labels)
    elif names is not None:
        # Validate even when no trace is supplied; typoed names paths must not be ignored.
        load_names(names)
        replay['warnings'].append('Names were supplied without task samples; no task names used.')
    return result


def _text_report(result):
    timeline = result['timeline']
    lines = [
        'CH12 offline replay: %d rows, %d valid readouts' %
        (timeline['row_count'], timeline['valid_readout_count']),
        'DMA > %d us: %d suspects; unknown DMA: %d' %
        (timeline['threshold_us'], timeline['suspect_count'], timeline['unknown_dma_count']),
        'Suspect rows (zero-based): %s' % ', '.join(map(str, timeline['suspect_rows'])),
        'Unwrap: %s; relative sensor period: %d us; missing slots estimate: %d' %
        (timeline['unwrap_basis'], timeline['period_us'], timeline['missing_sensor_slots_estimate']),
        timeline['phase_origin'],
        'Suspect sensor-slot phase mod16: ' + json.dumps(timeline['suspect_sensor_phase_mod16'], sort_keys=True),
    ]
    for event in timeline['events']:
        if event['suspect']:
            lines.append('  row=%d slot=%d readout_us=%d dma_us=%d' %
                         (event['row'], event['sensor_slot'], event['readout_us'], event['dma_duration_us']))
    lines.extend('WARNING: ' + warning for warning in timeline['warnings'])
    if result['task_trace'] is not None:
        lines.extend('WARNING: ' + warning for warning in result['task_trace']['warnings'])
    correlation = result['correlation']
    if correlation is not None:
        lines.append('TASK alignment: ' + json.dumps(correlation['alignment'], sort_keys=True))
        lines.append('TASK intervals/coverage: ' + json.dumps(correlation['intervals'], sort_keys=True))
        lines.append(correlation['interpretation'])
        if correlation['status'] == 'aligned':
            lines.append('Classes: ' + json.dumps(correlation['classes'], sort_keys=True))
            for task in correlation['tasks']:
                lines.append('Task exposure: ' + json.dumps(task, sort_keys=True))
            for frame in correlation['per_frame']:
                lines.append('Frame coverage: ' + json.dumps(frame, sort_keys=True))
    return '\n'.join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_requested = '--json' in argv
    parser = _ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--timeline', required=True, type=Path)
    parser.add_argument('--tasks', type=Path)
    parser.add_argument('--names', type=Path)
    parser.add_argument('--capture-ticks', type=Path,
                        help='M10X3T.BIN (otherwise auto-discover corresponding file)')
    parser.add_argument('--period-us', type=int, default=DEFAULT_PERIOD_US)
    parser.add_argument('--threshold-us', type=int, default=DEFAULT_THRESHOLD_US)
    parser.add_argument('--assert-no-stretch', action='store_true',
                        help='exit 1 if any valid DMA duration exceeds threshold')
    parser.add_argument('--json', action='store_true', help='emit one JSON object on stdout')
    try:
        args = parser.parse_args(argv)
        result = analyze_files(args.timeline, args.tasks, args.names, args.period_us,
                               args.threshold_us, args.capture_ticks)
    except (OSError, ValueError, struct.error) as exc:
        error = {'schema_version': 1, 'error': str(exc)}
        if json_requested:
            print(json.dumps(error, sort_keys=True))
        else:
            print('m10tasktrace: ' + str(exc), file=sys.stderr)
        return 2
    result['assert_no_stretch'] = args.assert_no_stretch
    result['assertion_failed'] = bool(args.assert_no_stretch and result['timeline']['suspect_count'])
    print(json.dumps(result, sort_keys=True, allow_nan=False) if args.json else _text_report(result))
    return 1 if result['assertion_failed'] else 0


if __name__ == '__main__':
    sys.exit(main())

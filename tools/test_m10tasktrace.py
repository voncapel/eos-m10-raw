#!/usr/bin/env python3
"""Pure offline tests: python3 -B -m unittest discover -s tools -p test_m10tasktrace.py -v."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import m10tasktrace as trace


def stamp(value):
    return trace.VALID | (value % trace.U20)


def row(start, duration=17000, encoder=28000, sd=30000):
    # Opaque address words intentionally look unlike time stamps.
    return (0xC0000001, stamp(start), stamp(start + duration),
            stamp(start + duration + 400), stamp(start + duration + 400 + encoder),
            stamp(start + 60000), stamp(start + 60000 + sd), 0xFFFFFFFF)


def timeline_bytes(rows, he_n=0, errors=None):
    return (struct.pack('<4I', trace.TLF_MAGIC, len(rows), 8, he_n) +
            struct.pack('<32I', *(errors or [0] * 32)) +
            b''.join(struct.pack('<8I', *item) for item in rows))


def ticks_bytes(ticks, writes=None):
    writes = writes or [0] * len(ticks)
    return struct.pack('<%dI' % (1 + 2 * len(ticks)), len(ticks), *ticks, *writes)


def tasks_bytes(records, start=0, stop=120000, period=1000, capacity=65536,
                anchor=trace.NO_ANCHOR, **fields):
    header = dict(zip(trace.TASK_FIELDS, (
        trace.TASK_MAGIC, 64, 8, len(records), capacity, period, 0x12345678,
        start, (start + stop) % trace.U20, stop, 0, 0, 10, 0, 153, anchor)))
    header.update(fields)
    return (struct.pack('<16I', *(header[key] for key in trace.TASK_FIELDS)) +
            b''.join(struct.pack('<2I', *sample) for sample in records))


def replay(rows, ticks=None, period=40000, threshold=22000):
    return trace.replay_timeline(trace.parse_timeline(timeline_bytes(rows)), period,
                                 threshold, ticks)


def correlate(rows, records, stop=120000, period=1000, start=0, anchor=0, names=None):
    timeline = replay(rows)
    tasks = trace.parse_tasks(tasks_bytes(records, start=start, stop=stop,
                                          period=period, anchor=anchor))
    alignment = trace.align_tasks(timeline, tasks)
    return trace.correlate_tasks(timeline, tasks, alignment, names)


class TimelineTests(unittest.TestCase):
    def test_readout_wrap_and_dma_encoder_sd_wrap(self):
        value = replay([row(trace.U20 - 10000, 23000), row(trace.U20 + 30000)])
        self.assertEqual([e['readout_us'] for e in value['events']], [0, 40000])
        self.assertEqual(value['suspect_rows'], [0])
        self.assertEqual(value['events'][0]['dma_duration_us'], 23000)
        self.assertEqual(value['events'][0]['encoder_duration_us'], 28000)
        self.assertEqual(value['events'][0]['sd_duration_us'], 30000)

    def test_skipped_sensor_frames_preserve_real_gap_and_phase(self):
        value = replay([row(12345), row(52350), row(172347)])
        self.assertEqual([e['sensor_slot'] for e in value['events']], [0, 1, 4])
        self.assertEqual([e['readout_us'] for e in value['events']], [0, 40005, 160002])
        self.assertEqual(value['events'][2]['phase_residual_us'], 2)
        self.assertEqual(value['missing_sensor_slots_estimate'], 2)
        self.assertIn('arbitrary', value['phase_origin'])

    def test_sensor_phase_mod16_uses_unwrapped_slots_not_row_index(self):
        start = trace.U20 - 10000
        value = replay([row(start, 23000), row(start + 40000),
                        row(start + 640000, 23000), row(start + 760000, 23000)])
        self.assertEqual([e['sensor_slot'] for e in value['events']], [0, 1, 16, 19])
        phases = value['suspect_sensor_phase_mod16']
        self.assertEqual(phases['counts']['0'], 2)
        self.assertEqual(phases['counts']['3'], 1)
        self.assertEqual(phases['counts']['2'], 0)
        self.assertEqual(phases['dominant_phases'], [0])
        self.assertEqual(phases['dominant_count'], 2)
        self.assertEqual(replay([row(0)])['suspect_sensor_phase_mod16']['dominant_phases'], [])

    def test_threshold_is_strictly_greater(self):
        value = replay([row(0, 22000), row(40000, 22001)])
        self.assertEqual(value['suspect_rows'], [1])

    def test_custom_period_threshold(self):
        value = replay([row(0, 200), row(10000, 201)], period=10000, threshold=200)
        self.assertEqual(value['suspect_rows'], [1])
        self.assertEqual(value['events'][1]['sensor_slot'], 1)

    def test_invalid_timestamps_not_zero_or_normal(self):
        rows = [row(100), list(row(40100)), list(row(80100))]
        rows[1][1] &= trace.MASK20
        rows[2][2] &= trace.MASK20
        value = replay(rows)
        self.assertEqual(value['invalid_readout_rows'], [1])
        self.assertEqual(value['events'][1]['readout_us'], 80000)
        self.assertEqual(value['events'][1]['classification'], 'unknown')
        self.assertEqual(value['unknown_dma_count'], 1)
        self.assertEqual(value['suspect_count'], 0)

    def test_invalid_encoder_sd_pairs_are_unknown(self):
        item = list(row(10))
        item[3] = 0
        item[6] = 0
        event = replay([item])['events'][0]
        self.assertIsNone(event['encoder_duration_us'])
        self.assertIsNone(event['sd_duration_us'])
        self.assertIsNotNone(event['sd_start_offset_us'])

    def test_addresses_ignored_even_valid_bit_set(self):
        item = list(row(42))
        item[0], item[7] = 0xFFFFFFFF, trace.VALID
        value = replay([item])
        self.assertEqual(value['events'][0]['readout_u20'], 42)
        self.assertEqual(value['events'][0]['readout_us'], 0)

    def test_empty_and_all_invalid_timeline(self):
        for rows in ([], [(0,) * 8]):
            value = replay(rows)
            self.assertEqual(value['events'], [])
            self.assertIsNone(value['first_readout_u20'])

    def test_identical_readouts_report_ambiguity(self):
        value = replay([row(10), row(10)])
        self.assertTrue(value['unwrap_ambiguities'])
        self.assertEqual(value['repeated_sensor_slot_rows'], [1])

    def test_coarse_ticks_recover_multiple_timer_turns(self):
        ticks = trace.parse_capture_ticks(ticks_bytes([80, 2520], [11, 22]))
        value = replay([row(900000), row(3340000)], ticks)
        self.assertEqual(value['events'][1]['readout_us'], 2440000)
        self.assertEqual(value['events'][1]['extra_timer_turns'], 2)
        self.assertEqual(value['events'][1]['sensor_slot'], 61)
        self.assertEqual(value['events'][1]['write_duration_us'], 22)
        self.assertEqual(value['unwrap_ambiguities'], [])

    def test_ticks_do_not_snap_normal_readout_jitter(self):
        ticks = trace.parse_capture_ticks(ticks_bytes([80, 130, 160]))
        value = replay([row(0), row(40005), row(80002)], ticks)
        self.assertEqual([e['readout_us'] for e in value['events']], [0, 40005, 80002])

    def test_coarse_tick_wrap(self):
        ticks = trace.parse_capture_ticks(ticks_bytes([0xFFFFFFF0, 24]))
        value = replay([row(10), row(40010)], ticks)
        self.assertEqual(value['events'][1]['readout_us'], 40000)

    def test_inconsistent_coarse_clock_reports_ambiguity(self):
        ticks = trace.parse_capture_ticks(ticks_bytes([0, 500]))
        value = replay([row(10), row(40010)], ticks)
        self.assertTrue(value['unwrap_ambiguities'])

    def test_insufficient_or_reverse_ticks_rejected(self):
        for ticks in ([0], [80, 40]):
            with self.subTest(ticks=ticks), self.assertRaises(trace.FormatError):
                replay([row(0), row(40000)], trace.parse_capture_ticks(ticks_bytes(ticks)))

    def test_invalid_parameter_ranges(self):
        for period, threshold in ((0, 22000), (-1, 22000), (40000, -1), (40000, trace.U20)):
            with self.subTest(period=period, threshold=threshold), self.assertRaises(ValueError):
                replay([], period=period, threshold=threshold)

    def test_more_errors_than_slots_are_explicit(self):
        parsed = trace.parse_timeline(timeline_bytes([row(0)], he_n=40, errors=list(range(32))))
        value = trace.replay_timeline(parsed)
        self.assertEqual(value['he_n'], 40)
        self.assertEqual(value['errors'], list(range(32)))
        self.assertTrue(any('truncated' in warning for warning in value['warnings']))

    def test_malformed_timeline(self):
        good = timeline_bytes([row(0)])
        variants = [b'', good[:143], good[:-1], good + b'\0',
                    struct.pack('<I', 0) + good[4:], good[:8] + struct.pack('<I', 7) + good[12:]]
        for value in variants:
            with self.subTest(size=len(value)), self.assertRaises(trace.FormatError):
                trace.parse_timeline(value)

    def test_malformed_capture_ticks(self):
        for value in (b'', b'\0', struct.pack('<I', 3), ticks_bytes([0]) + b'\0\0\0\0'):
            with self.subTest(value=value), self.assertRaises(trace.FormatError):
                trace.parse_capture_ticks(value)


class TaskParsingTests(unittest.TestCase):
    def test_parse_contract_current_address_is_opaque(self):
        tasks = trace.parse_tasks(tasks_bytes([(10, 0x80000001), (1010, 0)], stop=2000))
        self.assertEqual(tasks.header['current_task_addr'], 0x12345678)
        self.assertEqual(tasks.header['capacity'], 65536)
        self.assertEqual(tasks.records[0], (10, 0x80000001))
        self.assertEqual(tasks.records[1][1], 0)

    def test_empty_off_trace_period_zero(self):
        tasks = trace.parse_tasks(tasks_bytes([], stop=0, period=0))
        alignment = trace.align_tasks(replay([row(0)]), tasks)
        self.assertEqual(alignment['status'], 'unavailable')
        self.assertIn('No task samples', alignment['reason'])

    def test_invalid_task_headers(self):
        variants = [dict(magic=0), dict(header_bytes=60), dict(record_bytes=12),
                    dict(version=152), dict(capacity=0), dict(period_us=0),
                    dict(start_u20=trace.U20), dict(stop_u20=20),
                    dict(first_readout_elapsed_us=3000), dict(full=2)]
        for fields in variants:
            with self.subTest(fields=fields), self.assertRaises(trace.FormatError):
                trace.parse_tasks(tasks_bytes([(10, 1)], stop=2000, **fields))

    def test_invalid_sample_order_and_range(self):
        for records in ([(10, 1), (10, 2)], [(20, 1), (10, 2)], [(2001, 1)]):
            with self.subTest(records=records), self.assertRaises(trace.FormatError):
                trace.parse_tasks(tasks_bytes(records, stop=2000))

    def test_task_size_must_equal_count_not_capacity(self):
        good = tasks_bytes([(10, 1)], stop=2000)
        for data in (good[:63], good[:-1], good + b'\0' * 8):
            with self.subTest(size=len(data)), self.assertRaises(trace.FormatError):
                trace.parse_tasks(data)

    def test_unique_modulo_anchor_and_wrap(self):
        tasks = trace.parse_tasks(tasks_bytes([(10, 1)], start=trace.U20 - 100,
                                               stop=20000))
        alignment = trace.align_tasks(replay([row(200)]), tasks)
        self.assertEqual(alignment['status'], 'aligned')
        self.assertEqual(alignment['first_readout_elapsed_us'], 300)
        self.assertEqual(alignment['source'], 'modulo20_unique')

    def test_multiple_turn_alignment_is_not_hidden(self):
        tasks = trace.parse_tasks(tasks_bytes([(10, 1)], stop=3 * trace.U20))
        timeline = replay([row(1000)])
        alignment = trace.align_tasks(timeline, tasks)
        self.assertEqual(alignment['status'], 'ambiguous')
        self.assertEqual(alignment['candidate_offsets_us'], [1000, trace.U20 + 1000, 2 * trace.U20 + 1000])
        result = trace.correlate_tasks(timeline, tasks, alignment)
        self.assertEqual(result['tasks'], [])
        self.assertEqual(result['per_frame'], [])

    def test_validated_anchor_resolves_multiple_turns(self):
        anchor = 2 * trace.U20 + 1000
        tasks = trace.parse_tasks(tasks_bytes([(10, 1)], stop=3 * trace.U20,
                                               anchor=anchor))
        alignment = trace.align_tasks(replay([row(1000)]), tasks)
        self.assertEqual(alignment['status'], 'aligned')
        self.assertEqual(alignment['first_readout_elapsed_us'], anchor)
        self.assertEqual(alignment['source'], 'header_word15')

    def test_anchor_zero_is_real_not_reserved(self):
        tasks = trace.parse_tasks(tasks_bytes([(0, 1)], anchor=0))
        alignment = trace.align_tasks(replay([row(0)]), tasks)
        self.assertEqual(alignment['first_readout_elapsed_us'], 0)

    def test_bad_anchor_congruence_fails(self):
        tasks = trace.parse_tasks(tasks_bytes([(0, 1)], anchor=500))
        with self.assertRaisesRegex(trace.FormatError, 'congruence'):
            trace.align_tasks(replay([row(0)]), tasks)

    def test_anchor_on_invalid_row_zero_is_not_misapplied(self):
        tasks = trace.parse_tasks(tasks_bytes([(0, 1)], anchor=0))
        invalid = list(row(0))
        invalid[1] = 0
        alignment = trace.align_tasks(replay([invalid, row(40000)]), tasks)
        self.assertEqual(alignment['status'], 'unavailable')

    def test_no_possible_alignment(self):
        tasks = trace.parse_tasks(tasks_bytes([(0, 1)], stop=1000))
        alignment = trace.align_tasks(replay([row(2000)]), tasks)
        self.assertEqual(alignment['status'], 'unavailable')

    def test_uncertain_readout_unwrap_disables_correlation(self):
        tasks = trace.parse_tasks(tasks_bytes([(0, 1)], anchor=0))
        alignment = trace.align_tasks(replay([row(0), row(0)]), tasks)
        self.assertEqual(alignment['status'], 'unavailable')


class ExposureTests(unittest.TestCase):
    def test_time_weights_split_readout_boundary_not_sample_counts(self):
        result = correlate([row(0), row(40000, 23000)],
                           [(0, 1), (30000, 2), (50000, 1)], stop=80000, period=20000,
                           names={1: 'Capture', 2: 'Writer'})
        tasks = {task['task_ptr']: task for task in result['tasks']}
        one, two = tasks['0x00000001'], tasks['0x00000002']
        self.assertEqual(one['normal']['exposure_us'], 30000)
        self.assertEqual(two['normal']['exposure_us'], 10000)
        self.assertEqual(one['stretch']['exposure_us'], 30000)
        self.assertEqual(two['stretch']['exposure_us'], 10000)
        self.assertEqual(two['stretch_enrichment'], 1)
        self.assertEqual(one['name'], 'Capture')
        self.assertEqual(result['classes']['normal']['sample_count'], 2)
        self.assertEqual(result['classes']['stretch']['sample_count'], 1)
        self.assertEqual(one['normal']['sample_share'], 0.5)
        self.assertEqual(one['normal']['covered_share'], 0.75)
        self.assertIn('NOT causal proof', result['interpretation'])

    def test_long_missing_samples_are_capped_and_coverage_exposed(self):
        result = correlate([row(0), row(40000, 23000)], [(0, 1), (70000, 2)], stop=80000)
        self.assertEqual(result['intervals']['attributed_trace_us'], 6000)
        self.assertEqual(result['intervals']['over_cap_interval_count'], 2)
        self.assertEqual(result['classes']['normal']['coverage'], 3000 / 40000)
        self.assertEqual(result['classes']['stretch']['coverage'], 3000 / 40000)
        self.assertEqual(result['per_frame'][0]['uncovered_us'], 37000)
        self.assertEqual(result['per_frame'][1]['uncovered_us'], 37000)
        self.assertEqual(result['intervals']['gap_us'], 74000)

    def test_no_backfill_before_first_sample_and_last_hold_capped(self):
        result = correlate([row(0)], [(10000, 1)], stop=40000)
        self.assertEqual(result['per_frame'][0]['covered_us'], 3000)
        self.assertEqual(result['intervals']['gaps'][0]['reason'], 'before_first_sample')
        self.assertEqual(result['intervals']['gaps'][0]['end_us'], 10000)
        self.assertEqual(result['intervals']['interval_stats']['max_us'], 30000)

    def test_null_task_pointer_is_unattributed_not_a_task(self):
        result = correlate([row(0)], [(0, 0), (1000, 1)], stop=2000)
        self.assertEqual(result['per_frame'][0]['covered_us'], 1000)
        self.assertEqual(result['intervals']['gaps'][0]['reason'], 'null_task_pointer')
        self.assertFalse(any(task['task_ptr'] == '0x00000000' for task in result['tasks']))
        self.assertEqual(result['intervals']['unknown_nonirq_us'], 1000)
        self.assertEqual(result['intervals']['unknown_nonirq_sample_count'], 1)
        self.assertEqual(result['per_frame'][0]['unknown_nonirq_us'], 1000)
        self.assertEqual(result['classes']['normal']['unknown_nonirq_sample_count'], 1)
        self.assertEqual(result['classes']['normal']['sample_count'], 1)

    def test_real_sensor_gap_not_exposure_for_previous_frame(self):
        result = correlate([row(0), row(160000, 23000)], [(0, 1), (160000, 2)],
                           stop=200000, period=100000)
        self.assertEqual(result['sensor_gap_us_excluded'], 120000)
        self.assertEqual([frame['window_us'] for frame in result['per_frame']], [40000, 40000])
        self.assertEqual(result['classes']['normal']['covered_us'], 40000)
        self.assertEqual(result['classes']['stretch']['covered_us'], 40000)

    def test_partial_trace_after_stop_has_no_coverage(self):
        result = correlate([row(0), row(40000)], [(0, 1)], stop=10000, period=40000)
        self.assertEqual(result['per_frame'][0]['covered_us'], 10000)
        self.assertEqual(result['per_frame'][1]['covered_us'], 0)
        self.assertEqual(result['per_frame'][1]['coverage'], 0)

    def test_unknown_dma_does_not_contaminate_normal_class(self):
        invalid = list(row(0))
        invalid[2] = 0
        result = correlate([invalid], [(0, 1)], stop=40000, period=40000)
        self.assertEqual(result['classes']['normal']['window_us'], 0)
        self.assertEqual(result['classes']['unknown']['window_us'], 40000)
        self.assertIsNone(result['tasks'][0]['stretch_enrichment'])

    def test_empty_and_zero_duration_windows(self):
        result = correlate([row(0)], [(0, 1)], stop=0)
        self.assertEqual(result['per_frame'][0]['coverage'], 0)
        self.assertIsNone(result['intervals']['trace_coverage'])
        self.assertEqual(result['tasks'], [{'task_ptr': '0x00000001', 'name': None,
            'normal': {'exposure_us': 0, 'covered_share': None, 'window_share': 0,
                       'sample_count': 1, 'sample_share': 1},
            'stretch': {'exposure_us': 0, 'covered_share': None, 'window_share': None,
                        'sample_count': 0, 'sample_share': None},
            'unknown': {'exposure_us': 0, 'covered_share': None, 'window_share': None,
                        'sample_count': 0, 'sample_share': None},
            'stretch_enrichment': None}])


class FileAndCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='m10tasktrace-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.tlf = self.root / 'test_M10TLF.BIN'
        self.tlf.write_bytes(timeline_bytes([row(0), row(40000, 23000)]))

    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = trace.main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_timeline_only_json_and_red_assertion(self):
        args = ['--timeline', str(self.tlf), '--json']
        code, out, err = self.invoke(args)
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        self.assertEqual(json.loads(out)['timeline']['suspect_rows'], [1])
        code, out, err = self.invoke(args + ['--assert-no-stretch'])
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(out)['assertion_failed'])

    def test_green_assertion_and_text_report(self):
        code, out, err = self.invoke(['--timeline', str(self.tlf), '--threshold-us', '24000',
                                      '--assert-no-stretch'])
        self.assertEqual(code, 0)
        self.assertIn('0 suspects', out)
        self.assertIn('arbitrary', out)
        self.assertEqual(err, '')

    def test_json_format_errors_and_missing_file_exit_two(self):
        for path in (self.root / 'missing', self.root / 'bad'):
            if path.name == 'bad':
                path.write_bytes(b'broken')
            code, out, err = self.invoke(['--timeline', str(path), '--json'])
            self.assertEqual(code, 2)
            self.assertIn('error', json.loads(out))
            self.assertEqual(err, '')

    def test_invalid_numeric_option_exit_two(self):
        code, out, err = self.invoke(['--timeline', str(self.tlf), '--period-us', '0', '--json'])
        self.assertEqual(code, 2)
        self.assertIn('error', json.loads(out))

    def test_argument_errors_also_emit_json(self):
        for args in (['--json'], ['--timeline', str(self.tlf), '--period-us', 'bad', '--json'],
                     ['--timeline', str(self.tlf), '--unknown', '--json']):
            with self.subTest(args=args):
                code, out, err = self.invoke(args)
                self.assertEqual(code, 2)
                self.assertIn('error', json.loads(out))
                self.assertEqual(err, '')

    def test_discover_ticks_and_explicit_override(self):
        auto = self.root / 'test_M10X3T.BIN'
        auto.write_bytes(ticks_bytes([0, 40]))
        result = trace.analyze_files(self.tlf)
        self.assertEqual(result['capture_ticks_file'], str(auto))
        self.assertEqual(result['timeline']['unwrap_basis'], 'coarse_ms_capture_ticks')
        explicit = self.root / 'other.bin'
        explicit.write_bytes(ticks_bytes([0, 40]))
        self.assertEqual(trace.analyze_files(self.tlf, capture_ticks=explicit)['capture_ticks_file'], str(explicit))

    def test_bad_discovered_ticks_not_silently_ignored(self):
        (self.root / 'test_M10X3T.BIN').write_bytes(b'bad')
        with self.assertRaises(trace.FormatError):
            trace.analyze_files(self.tlf)

    def test_files_with_tasks_names_and_health_warnings(self):
        tasks = self.root / 'tasks.bin'
        tasks.write_bytes(tasks_bytes([(0, 1), (40000, 2)], period=40000, stop=80000,
                                       anchor=0, full=1, timer_bad_count=2))
        names = self.root / 'names.json'
        names.write_text(json.dumps({'0x00000001': 'Capture', '00000002': 'Writer'}))
        result = trace.analyze_files(self.tlf, tasks=tasks, names=names)
        self.assertEqual(result['correlation']['status'], 'aligned')
        self.assertEqual(result['correlation']['tasks'][0]['name'], 'Capture')
        self.assertEqual(len(result['task_trace']['warnings']), 2)
        self.assertIn('TASK alignment', trace._text_report(result))

    def test_names_validation(self):
        names = self.root / 'names.json'
        for value in ([], {'potato': 'bad'}, {'0x100000000': 'bad'}, {'1': 20},
                      {'0x1': 'A', '0001': 'duplicate'}):
            names.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(trace.FormatError):
                trace.load_names(names)

    def test_names_without_tasks_validate_and_warn(self):
        names = self.root / 'names.json'
        names.write_text('{"0x1":"Capture"}')
        result = trace.analyze_files(self.tlf, names=names)
        self.assertTrue(any('without task' in w for w in result['timeline']['warnings']))


if __name__ == '__main__':
    unittest.main()

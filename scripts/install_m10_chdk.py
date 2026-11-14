#!/usr/bin/env python3
"""
CHDK install helper for the Canon EOS M10 (macOS).
- Detects the exact firmware sub-version (110d, 110f, 110g, 111a) from the Canon MakerNote
  tag 0x001e (FirmwareRevision) of the photos in DCIM/.
- Checks the card file system (FAT32 is needed for the BOOTDISK autoboot; exFAT will not boot).
- Unzips the matching CHDK build from ../builds/ (download it from the CHDK autobuild server first).
"""
import os
import sys
import glob
import struct
import zipfile
import subprocess

BUILDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "builds"))

BUILD_MAP = {
    "110d": "m10-110d-1.7.0-6358-full_BETA.zip",
    "110f": "m10-110f-1.7.0-6358-full_BETA.zip",
    "110g": "m10-110g-1.7.0-6358-full_BETA.zip",
    "111a": "m10-111a-1.7.0-6358-full_ALPHA.zip",
}


def parse_canon_fw_rev_from_jpeg(fpath: str):
    """Read Canon MakerNote tag 0x001e (FirmwareRevision, e.g. 0x01100400 -> '110d')."""
    try:
        with open(fpath, "rb") as f:
            data = f.read(131072)
        if b"Canon EOS M10" not in data:
            return None
        idx = data.find(b"Exif\x00\x00")
        if idx < 0:
            return None
        tiff = data[idx + 6 :]
        endian = "<" if tiff[:2] == b"II" else ">"

        def read_ifd(offset):
            count = struct.unpack_from(endian + "H", tiff, offset)[0]
            entries = {}
            for i in range(count):
                tag, typ, cnt, val_off = struct.unpack_from(endian + "HHII", tiff, offset + 2 + i * 12)
                entries[tag] = (typ, cnt, val_off)
            return entries

        ifd0 = read_ifd(struct.unpack_from(endian + "I", tiff, 4)[0])
        if 0x8769 not in ifd0:
            return None
        exif_ifd = read_ifd(ifd0[0x8769][2])
        if 0x927C not in exif_ifd:
            return None
        mn = read_ifd(exif_ifd[0x927C][2])
        if 0x001E not in mn:
            return None
        rev = mn[0x001E][2]  # e.g. 0x01100400
        maj = (rev >> 24) & 0xFF
        minor = (rev >> 16) & 0xFF
        sub_idx = (rev >> 8) & 0xFF
        if 1 <= sub_idx <= 26:
            letter = chr(ord("a") + sub_idx - 1)
            return f"{maj:x}{minor:02x}{letter}"
    except Exception:
        return None
    return None


def detect_fw_from_dcim(volume_path: str):
    dcim = os.path.join(volume_path, "DCIM")
    if not os.path.isdir(dcim):
        return None, None
    files = sorted(
        glob.glob(os.path.join(dcim, "**", "*.JPG"), recursive=True)
        + glob.glob(os.path.join(dcim, "**", "*.jpg"), recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )
    for fpath in files[:20]:
        fw = parse_canon_fw_rev_from_jpeg(fpath)
        if fw:
            return fw, fpath
    return None, None


def get_fs_type(volume_path: str):
    try:
        out = subprocess.check_output(["diskutil", "info", volume_path], text=True)
        for line in out.splitlines():
            if "File System Personality:" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "Unknown"


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 install_m10_chdk.py /Volumes/CARD_NAME [--check | 110d|110f|110g|111a]")
        sys.exit(0)

    volume_path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.isdir(volume_path):
        print(f"Error: volume '{volume_path}' does not exist.")
        sys.exit(1)

    fs_type = get_fs_type(volume_path)
    detected_fw, sample_photo = detect_fw_from_dcim(volume_path)

    print(f"Target volume      : {volume_path}")
    print(f"File system        : {fs_type}")
    if detected_fw:
        print(f"M10 firmware       : {detected_fw} (from {os.path.basename(sample_photo)})")
    else:
        print("M10 firmware       : no EOS M10 JPEG found in DCIM/")

    if "ExFAT" in fs_type:
        print(
            "\n[WARNING] The card is formatted exFAT.\n"
            "The EOS M10 boot code (MakeSDCardBootable) only autoboots from FAT32 or FAT16\n"
            "(BOOTDISK signature at offset 0x1E0).\n"
            "Back up DCIM/, then reformat the card as FAT32 (MBR) before installing."
        )

    if mode == "--check":
        return

    fw_ver = mode if (mode and mode in BUILD_MAP) else detected_fw
    if not fw_ver or fw_ver not in BUILD_MAP:
        print(f"Error: firmware version unknown ({fw_ver}). Pass 110d, 110f, 110g or 111a explicitly.")
        sys.exit(1)

    zip_path = os.path.join(BUILDS_DIR, BUILD_MAP[fw_ver])
    print(f"\nExtracting {os.path.basename(zip_path)} to {volume_path}...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(volume_path)
    print("[OK] CHDK files copied to the card.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Put a ``synaps_native`` wheel inside a platform wheel of project ``synaps``.

PyPI has ``synaps`` and no ``synaps_native``. The release environment's
trusted publisher is for ``synaps``, so uploading the maturin wheel under
its own name is rejected. The extension stays importable as
``synaps_native`` when its files ride in a ``synaps`` wheel with the same
Python and platform tags.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    token = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={token}"


def _metadata_value(metadata: str, key: str) -> str:
    prefix = f"{key}:"
    for line in metadata.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"wheel METADATA has no {key}")


def _wheel_tags(text: str) -> list[str]:
    return [line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("Tag:")]


def _is_pure(wheel_text: str) -> bool:
    return any(line.strip() == "Root-Is-Purelib: true" for line in wheel_text.splitlines())


def _record(payload: dict[str, bytes], record_name: str) -> bytes:
    rows: list[tuple[str, str, str]] = []
    for name in sorted(payload):
        if name == record_name:
            continue
        data = payload[name]
        rows.append((name, _record_hash(data), str(len(data))))
    rows.append((record_name, "", ""))
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue().encode("utf-8")


def merge_wheel(pure: Path, native: Path, out_dir: Path) -> Path:
    """Build ``synaps-<version>-<native tags>.whl`` containing both trees."""
    with zipfile.ZipFile(pure) as pure_zip, zipfile.ZipFile(native) as native_zip:
        pure_names = pure_zip.namelist()
        meta_name = next(name for name in pure_names if name.endswith(".dist-info/METADATA"))
        metadata = pure_zip.read(meta_name).decode("utf-8")
        project = _metadata_value(metadata, "Name")
        version = _metadata_value(metadata, "Version")
        native_wheel = next(
            name for name in native_zip.namelist() if name.endswith(".dist-info/WHEEL")
        )
        tags = _wheel_tags(native_zip.read(native_wheel).decode("utf-8"))
        if not tags:
            raise ValueError(f"{native.name}: native wheel has no Tag")
        dist_info = meta_name.split(".dist-info/", 1)[0] + ".dist-info"
        payload: dict[str, bytes] = {}
        for name in pure_names:
            if name.endswith(".dist-info/RECORD") or name.endswith(".dist-info/WHEEL"):
                continue
            payload[name] = pure_zip.read(name)
        for name in native_zip.namelist():
            if ".dist-info/" in name:
                continue
            payload[name] = native_zip.read(name)
        wheel_text = (
            "Wheel-Version: 1.0\n"
            "Generator: synaps-native-merge\n"
            "Root-Is-Purelib: false\n"
            + "".join(f"Tag: {tag}\n" for tag in tags)
        )
        payload[f"{dist_info}/WHEEL"] = wheel_text.encode("utf-8")
        record_name = f"{dist_info}/RECORD"
        payload[record_name] = _record(payload, record_name)
        filename = f"{project.replace('-', '_').lower()}-{version}-{tags[0]}.whl"
        out_dir.mkdir(parents=True, exist_ok=True)
        destination = out_dir / filename
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for name, data in sorted(payload.items()):
                out.writestr(name, data)
        return destination


def _pure_wheel(directory: Path) -> Path:
    found: list[Path] = []
    for wheel in sorted(directory.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            wheel_name = next(
                name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")
            )
            if _is_pure(archive.read(wheel_name).decode("utf-8")):
                found.append(wheel)
    if len(found) != 1:
        raise SystemExit(f"{directory}: expected one pure wheel, found {found}")
    return found[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pure_dir", type=Path)
    parser.add_argument("native_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    pure = _pure_wheel(args.pure_dir)
    natives = sorted(args.native_dir.glob("*.whl"))
    if not natives:
        raise SystemExit(f"{args.native_dir}: no native wheels")
    for native in natives:
        print(merge_wheel(pure, native, args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

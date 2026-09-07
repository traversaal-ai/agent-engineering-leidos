"""Upload safety checks that must run *before* a parser touches the bytes.

System Design Section 6.5 ranks upload validation third, and calls out zip-bomb
protection specifically — because PPTX and XLSX are not really documents, they are
zip archives. A 40 KB .xlsx can expand to gigabytes, and a parser handed that file
will happily try, taking the whole process down with it. Since Axis runs as one
process during a live demo, an OOM here is not a failed upload; it is a dead
classroom.

The defence is to read the archive's *directory* — which lists uncompressed sizes
without decompressing anything — and refuse before any parsing begins.
"""

from __future__ import annotations

import io
import zipfile

from ai_backend.errors import IngestionError

# Formats that are secretly zip archives.
ZIP_BACKED_SUFFIXES = frozenset({".pptx", ".xlsx", ".docx"})


def assert_safe_archive(
    filename: str, data: bytes, *, max_uncompressed_bytes: int
) -> None:
    """Refuse an archive that would expand past the configured ceiling.

    Reads only the central directory, so this costs nothing on a normal file and
    cannot itself be exploited by the bomb it is checking for.

    Also refuses absolute or parent-relative member paths. Nothing in Axis writes
    archive members to disk today, so a traversal is not currently exploitable —
    but the check is one line, and the next person to add an extraction step
    should inherit it rather than have to remember it.
    """
    suffix = _suffix(filename)
    if suffix not in ZIP_BACKED_SUFFIXES:
        return

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = 0
            for member in archive.infolist():
                name = member.filename
                if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                    raise IngestionError(
                        f"{filename!r} contains an unsafe internal path and was "
                        f"not opened.",
                        detail=f"Refused member: {name!r}",
                    )

                total += member.file_size
                # Checked inside the loop, so a bomb is caught on the member that
                # crosses the line rather than after summing a directory with a
                # million entries.
                if total > max_uncompressed_bytes:
                    raise IngestionError(
                        f"{filename!r} expands to more than "
                        f"{max_uncompressed_bytes // (1024 * 1024)} MB and was not "
                        f"opened.",
                        detail=(
                            "Office documents are zip archives, so a small file "
                            "can expand enormously. Raise "
                            "AXIS_UPLOAD__MAX_UNCOMPRESSED_BYTES if this file is "
                            "genuinely this large."
                        ),
                    )
    except zipfile.BadZipFile as exc:
        raise IngestionError(
            f"{filename!r} is not a readable {suffix} file.",
            detail=str(exc),
        ) from exc


def _suffix(filename: str) -> str:
    _, _, ext = filename.rpartition(".")
    return f".{ext.lower()}" if ext else ""

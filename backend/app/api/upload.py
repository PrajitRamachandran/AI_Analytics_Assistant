
from pathlib import Path
from uuid import uuid4
import hashlib
from zipfile import ZipFile, BadZipFile

import shutil

from fastapi import APIRouter, File, HTTPException, UploadFile
from openpyxl import load_workbook

from app.core.database import get_db_connection
from app.core.dataset_state import ensure_state_schema

router = APIRouter(prefix="/api", tags=["Upload"])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"

MAX_FILE_SIZE = 25 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


@router.post("/upload")
async def upload_excel(file: UploadFile = File(...)):

    original_filename = (
        (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    )

    if not original_filename:
        raise HTTPException(
            status_code=400,
            detail="No filename provided."
        )

    if Path(original_filename).suffix.lower() != ".xlsx":
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx files are currently supported."
        )

    dataset_id = str(uuid4())
    dataset_dir = UPLOAD_DIR / dataset_id
    saved_file = dataset_dir / "workbook.xlsx"

    try:
        dataset_dir.mkdir(parents=True, exist_ok=False)

        file_size = 0
        digest = hashlib.sha256()

        with saved_file.open("wb") as output:
            while chunk := await file.read(CHUNK_SIZE):
                file_size += len(chunk)

                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the maximum size of 25 MB."
                    )

                output.write(chunk)
                digest.update(chunk)

        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty."
            )

        # Validate XLSX ZIP structure
        try:
            with ZipFile(saved_file, "r") as workbook_zip:
                required_files = {
                    "[Content_Types].xml",
                    "xl/workbook.xml"
                }

                if not required_files.issubset(
                    set(workbook_zip.namelist())
                ):
                    raise ValueError("Invalid XLSX structure.")

        except (BadZipFile, ValueError):
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is not a valid XLSX workbook."
            )

        # Verify workbook readability
        try:
            workbook = load_workbook(
                saved_file,
                read_only=True,
                data_only=True
            )
            workbook.close()

        except Exception:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is not a readable Excel workbook."
            )

        ensure_state_schema()
        content_sha256 = digest.hexdigest()

        # Save dataset metadata in PostgreSQL
        try:
            with get_db_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO datasets (
                            dataset_id,
                            filename,
                            file_size,
                            storage_path,
                            status,
                            content_sha256
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            dataset_id,
                            original_filename,
                            file_size,
                            str(saved_file.resolve()),
                            "uploaded",
                            content_sha256
                        )
                    )

        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise HTTPException(
                    status_code=409,
                    detail="File already exists. This exact workbook has already been uploaded.",
                ) from exc
            raise HTTPException(
                status_code=500,
                detail="File was validated, but its metadata could not be saved to the database."
            ) from exc

        return {
            "status": "success",
            "message": "Excel file uploaded successfully.",
            "dataset_id": dataset_id,
            "filename": original_filename,
            "size_bytes": file_size
        }

    except HTTPException:
        shutil.rmtree(dataset_dir, ignore_errors=True)
        raise

    except Exception:
        shutil.rmtree(dataset_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while uploading the file."
        )

    finally:
        await file.close()

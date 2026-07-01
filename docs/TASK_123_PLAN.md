# TASK_123_PLAN.md

## Goal

Harden the SQLite MVP backup/restore path with optional authenticated backup
encryption.

This task reduces an operational limitation from the technical specification:
production backups must be encrypted. It does not add scheduled backups,
managed object storage, PostgreSQL backup/restore, or a production worker.

## Scope

- Add `scripts/backup_crypto.py`.
- Add encrypted SQLite backup support to `scripts/backup_sqlite.py`.
- Add encrypted SQLite restore support to `scripts/restore_sqlite.py`.
- Keep existing plaintext backup/restore behavior backward compatible.
- Add tests for encrypted backup success, missing key, wrong key, ciphertext
  tampering, and encrypted retention.

## Encryption Policy

- Algorithm: `cryptography.fernet.Fernet`.
- Backup key source: `OPENJSON_BACKUP_ENCRYPTION_KEY` or explicit function/CLI
  argument.
- The key is never written into the backup manifest.
- Encrypted backup files use `.sqlite3.enc`.
- The manifest stores:
  - ciphertext size and SHA-256 at the top level;
  - `encryption.enabled`;
  - `encryption.algorithm`;
  - key environment variable name;
  - plaintext size and SHA-256 for post-decryption verification.

## Backup Flow

1. Create a temporary plaintext SQLite backup.
2. Run combined database integrity checks against the plaintext backup.
3. If encryption is enabled, encrypt the plaintext backup into `.sqlite3.enc`.
4. Delete the temporary plaintext backup.
5. Write the manifest with ciphertext and plaintext verification metadata.
6. Apply retention only after the new backup passes integrity checks.

## Restore Flow

1. Verify adjacent manifest JSON when present.
2. Verify backup file ciphertext size and SHA-256.
3. If encrypted, require the backup encryption key.
4. Decrypt into a temporary SQLite file.
5. Verify decrypted plaintext size and SHA-256.
6. Restore into the target database.
7. Run combined database integrity checks on the restored DB.
8. Delete temporary decrypted files.

## Commands

Generate a key:

```powershell
python scripts\backup_sqlite.py --generate-encryption-key
```

Create encrypted backup:

```powershell
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\backup_sqlite.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --encrypt `
  --retention-count 7
```

Restore encrypted backup:

```powershell
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\restore_sqlite.py `
  --backup-path "D:\OpenJson\backups\openjson-backup-<timestamp>.sqlite3.enc" `
  --target-db-path "D:\OpenJson\restored.sqlite3"
```

## Exclusions

- No automatic daily scheduler.
- No remote object storage upload.
- No PostgreSQL backup implementation.
- No key-management service integration.
- No secret rotation workflow.

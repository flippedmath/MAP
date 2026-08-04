# Database promote (local → live)

App tables are largely `managed = False`. Schema is applied with SQL/`pg_dump --schema-only`, not Django `makemigrations` for those tables.

## First live bring-up (this project)

1. **Schema only** from local Postgres into live.
2. **Reference catalogs** if empty after schema-only: `entity_type`, `assessment_option_group`.
3. `manage.py migrate` for Django internal tables.
4. Create IT users (`admin`, `admin2`), then `setup_collaboration_groups` and `setup_folders`.
5. Promote Public Library unit **Unit 1-A Tests: Polynomial and Rational Functions** (subtree + media) with owners remapped to `admin` and ACL to live `public` group.

## Identify a Public Library share root

```sql
SELECT bg.id, bg.name, bg.parent, bg.owner
FROM branch_group bg
JOIN users_group ug ON ug.branch_id = bg.id
JOIN permission_group pg ON pg.id = ug.permission_group
WHERE pg.name = 'public'
  AND bg.name = 'Unit 1-A Tests: Polynomial and Rational Functions';
```

Copy the recursive `branch_group` tree and payload tables (`assessment`, `assessment_question_group`, `custom_question_distribution`, `problem`, `question_block`, `entity_segment`, `cqd_pair`, `assessment_options`, …). Rsync referenced `media/content_images/` files.

## Rules

- Treat promotes as **explicit, one-way, reviewed**.
- Do not point local day-to-day `.env` at the live database.
- `pg_dump` does not copy media files; rsync separately.
- Exclude attempts, grades, notifications, tickets, invites unless intentionally promoted.

## Helper script

See `math_assessment_platform/scripts/promote_public_unit.sh` for exporting one named public unit from local Postgres.

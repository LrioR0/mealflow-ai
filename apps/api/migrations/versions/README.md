# Database migrations

Create the first migration after the V1 data model review:

```text
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

The development app currently calls `create_all` so the scaffold starts immediately. Replace that convenience with migrations before shared deployment.

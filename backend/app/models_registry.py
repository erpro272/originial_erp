"""Import every module's models so SQLAlchemy metadata (and Alembic) see all tables."""

import app.catalog.models
import app.core.models
import app.customers.models
import app.invoices.models
import app.orders.models  # noqa: F401

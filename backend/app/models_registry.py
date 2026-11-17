"""Import every module's models so SQLAlchemy metadata (and Alembic) see all tables."""

import app.ai.assistant.models
import app.ai.rag.models
import app.billing.models
import app.catalog.models
import app.core.models
import app.customers.models
import app.invoices.models
import app.orders.models
import app.planning.models
import app.purchasing.models  # noqa: F401

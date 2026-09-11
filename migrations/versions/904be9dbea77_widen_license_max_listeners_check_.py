"""widen license max_listeners check constraint for new tiers

Revision ID: 904be9dbea77
Revises: ba2c5f3a9bf8
Create Date: 2026-09-11 18:41:34.716608
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '904be9dbea77'
down_revision = 'ba2c5f3a9bf8'
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint(
        "ck_license_max_listeners_allowed", "licenses", type_="check"
    )
    op.create_check_constraint(
        "ck_license_max_listeners_allowed",
        "licenses",
        "max_listeners IN (5,10,15,25,35,50,100)",
    )


def downgrade():
    # NB: fails if any row already has max_listeners in the newly-added
    # values (5,15,50) — expected, since those tiers didn't exist before.
    op.drop_constraint(
        "ck_license_max_listeners_allowed", "licenses", type_="check"
    )
    op.create_check_constraint(
        "ck_license_max_listeners_allowed",
        "licenses",
        "max_listeners IN (10,25,35,100)",
    )

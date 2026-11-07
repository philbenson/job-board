from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    UniqueConstraint,
)

from job_board.models import NAMING_CONVENTION


def test_a_constraint_over_several_columns_is_named_after_all_of_them() -> None:
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    Table("parents", metadata, Column("a", Integer), Column("b", Integer))
    children = Table(
        "children",
        metadata,
        Column("a", Integer),
        Column("b", Integer),
        UniqueConstraint("a", "b"),
        ForeignKeyConstraint(["a", "b"], ["parents.a", "parents.b"]),
        Index(None, "a", "b"),
    )

    names = {type(constraint).__name__: constraint.name for constraint in children.constraints}
    (index,) = children.indexes

    assert names["UniqueConstraint"] == "uq_children_a_b"
    assert names["ForeignKeyConstraint"] == "fk_children_a_b_parents"
    assert index.name == "ix_children_a_children_b"

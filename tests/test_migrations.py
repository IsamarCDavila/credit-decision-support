from alembic import command
from alembic.config import Config
from conftest import ROOT
from sqlalchemy import text


def test_migration_round_trip_preserves_unrelated_tables(database):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with database.begin() as conn:
        conn.execute(text("CREATE TABLE unrelated_fixture (id int)"))
    command.downgrade(config, "base")
    with database.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('unrelated_fixture')")).scalar_one()
        assert conn.execute(text("SELECT to_regclass('cases')")).scalar_one() is None
    command.upgrade(config, "head")
    with database.begin() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0003_policy_engine"
        )
        conn.execute(text("DROP TABLE unrelated_fixture"))

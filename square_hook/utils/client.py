import os
import sqlite3
from dotenv import load_dotenv
from square import Square
from square.environment import SquareEnvironment

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

def get_db():
    """Connect directly to the SQLite database with foreign keys enabled."""
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'inventory.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def get_square_client():
    env_input = os.getenv('SQUARE_ENVIRONMENT', 'sandbox').lower()
    access_token = os.getenv('SQUARE_ACCESS_TOKEN')
    
    if not access_token:
        return None

    environment = SquareEnvironment.PRODUCTION if env_input == 'production' else SquareEnvironment.SANDBOX

    return Square(
        token=access_token,
        environment=environment
    )
#!/usr/bin/env python3
import random
import subprocess
import time
import os
import signal
import sys
import psycopg2
import mysql.connector
import uuid
import atexit
from datetime import datetime
from flask import Flask, render_template, request, session
from splitio import get_factory
from splitio.exceptions import TimeoutException
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))

# Initialize Split.io client
split_api_key = os.getenv('SPLITIO_SDK_KEY')
if not split_api_key:
    print("WARNING: SPLITIO_SDK_KEY environment variable not set")
    split_api_key = "localhost"  # Use localhost mode if no API key

# Initialize Split factory
factory = get_factory(split_api_key, config={"impressionsMode": "optimized"})
try:
    factory.block_until_ready(5)  # wait up to 5 seconds
except TimeoutException:
    print("WARNING: Split.io client initialization timed out")

split_client = factory.client()

class DatabaseManager:
    def __init__(self):
        self.postgres_container = "postgres-test"
        self.mariadb_container = "mariadb-test"
        self.postgres_port = 5432
        self.mariadb_port = 3306
        self.postgres_password = "postgres"
        self.mariadb_password = "mariadb"
        self.database_name = "performance_test"
        self.containers_started = False
        self.data_loaded = False

    def ensure_containers_running(self):
        """Make sure containers are running, start them if needed"""
        if self.containers_started:
            return
        
        print("Starting PostgreSQL container...")
        try:
            # Check if container exists and is running
            result = subprocess.run(["podman", "ps", "-q", "-f", f"name={self.postgres_container}"], 
                                  capture_output=True, text=True)
            if not result.stdout.strip():
                # Container not running, start it
                subprocess.run([
                    "podman", "run", "--name", self.postgres_container, 
                    "-e", f"POSTGRES_PASSWORD={self.postgres_password}",
                    "-e", f"POSTGRES_DB={self.database_name}",
                    "-p", f"{self.postgres_port}:5432",
                    "-d", "postgres:latest"
                ], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error starting PostgreSQL container: {e}")
            raise
        
        print("Starting MariaDB container...")
        try:
            # Check if container exists and is running
            result = subprocess.run(["podman", "ps", "-q", "-f", f"name={self.mariadb_container}"], 
                                  capture_output=True, text=True)
            if not result.stdout.strip():
                # Container not running, start it
                subprocess.run([
                    "podman", "run", "--name", self.mariadb_container,
                    "-e", f"MYSQL_ROOT_PASSWORD={self.mariadb_password}",
                    "-e", f"MYSQL_DATABASE={self.database_name}",
                    "-p", f"{self.mariadb_port}:3306",
                    "-d", "mariadb:latest"
                ], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error starting MariaDB container: {e}")
            raise
        
        # Wait for containers to be ready
        print("Waiting for containers to be ready...")
        time.sleep(15)
        self.containers_started = True

    def load_test_data(self, data_size=100000):
        """Create test tables and populate with identical data"""
        if self.data_loaded:
            return
            
        print(f"Creating test data with {data_size} records...")
        
        # Connect to PostgreSQL
        pg_conn = psycopg2.connect(
            host="localhost",
            port=self.postgres_port,
            database=self.database_name,
            user="postgres",
            password=self.postgres_password
        )
        pg_cursor = pg_conn.cursor()
        
        # Create PostgreSQL table
        pg_cursor.execute("DROP TABLE IF EXISTS test_table;")
        pg_cursor.execute("""
            CREATE TABLE test_table (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50),
                value NUMERIC(10,2),
                created_at TIMESTAMP
            );
        """)
        
        # Create batch insert for PostgreSQL
        insert_sql = "INSERT INTO test_table (name, value, created_at) VALUES "
        values = []
        for i in range(data_size):
            values.append(f"('item{i}', {i * 1.5}, TIMESTAMP '2023-01-01' + '{i} hours'::interval)")
        
        # Execute in batches of 1000 to avoid query size limits
        batch_size = 1000
        for i in range(0, len(values), batch_size):
            batch_values = values[i:i+batch_size]
            pg_cursor.execute(insert_sql + ",".join(batch_values))
        
        pg_conn.commit()
        pg_cursor.close()
        pg_conn.close()
        
        # Connect to MariaDB (wait a bit longer to ensure it's ready)
        retries = 0
        mariadb_conn = None
        while retries < 5:
            try:
                mariadb_conn = mysql.connector.connect(
                    host="localhost",
                    port=self.mariadb_port,
                    database=self.database_name,
                    user="root",
                    password=self.mariadb_password
                )
                break
            except mysql.connector.Error:
                retries += 1
                print(f"Waiting for MariaDB to be ready (attempt {retries})...")
                time.sleep(5)
                
        if not mariadb_conn:
            raise Exception("Failed to connect to MariaDB")
            
        mariadb_cursor = mariadb_conn.cursor()
        
        # Create MariaDB table
        mariadb_cursor.execute("DROP TABLE IF EXISTS test_table;")
        mariadb_cursor.execute("""
            CREATE TABLE test_table (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(50),
                value DECIMAL(10,2),
                created_at DATETIME
            );
        """)
        
        # Create batch insert for MariaDB
        insert_sql = "INSERT INTO test_table (name, value, created_at) VALUES "
        values = []
        for i in range(data_size):
            # Format datetime for MariaDB
            dt = datetime(2023, 1, 1)
            dt = dt.replace(hour=i % 24)
            dt_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            values.append(f"('item{i}', {i * 1.5}, '{dt_str}')")
        
        # Execute in batches
        for i in range(0, len(values), batch_size):
            batch_values = values[i:i+batch_size]
            mariadb_cursor.execute(insert_sql + ",".join(batch_values))
        
        mariadb_conn.commit()
        mariadb_cursor.close()
        mariadb_conn.close()
        
        print("Test data created successfully in both databases.")
        self.data_loaded = True

    def run_query(self, query, db_type):
        """Run query on specified database and return results and execution time"""
        if db_type == "postgres":
            conn = psycopg2.connect(
                host="localhost",
                port=self.postgres_port,
                database=self.database_name,
                user="postgres",
                password=self.postgres_password
            )
        else:  # mariadb
            conn = mysql.connector.connect(
                host="localhost",
                port=self.mariadb_port,
                database=self.database_name,
                user="root",
                password=self.mariadb_password
            )
        
        cursor = conn.cursor()
        
        start_time = time.time()
        cursor.execute(query)
        results = cursor.fetchall()
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Get column names
        if db_type == "postgres":
            column_names = [desc[0] for desc in cursor.description]
        else:
            column_names = [desc[0] for desc in cursor.description]
        
        cursor.close()
        conn.close()
        
        return {
            "execution_time": execution_time,
            "results": results,
            "column_names": column_names
        }

    def cleanup(self):
        """Stop and remove containers"""
        if not self.containers_started:
            return
            
        print("Cleaning up containers...")
        subprocess.run(["podman", "stop", self.postgres_container], check=False)
        subprocess.run(["podman", "stop", self.mariadb_container], check=False)
        subprocess.run(["podman", "rm", self.postgres_container], check=False)
        subprocess.run(["podman", "rm", self.mariadb_container], check=False)
        print("Cleanup complete.")
        self.containers_started = False
        self.data_loaded = False


# Create a global database manager
#db_manager = DatabaseManager()
db_manager = DatabaseManager()


# Initialize containers at startup
print("Starting containers at application startup...")
try:
    db_manager.ensure_containers_running()
    print("Containers started successfully")
    print("Loading test data...")
    db_manager.load_test_data()
    print("Test data loaded successfully")
except Exception as e:
    print(f"Error initializing containers: {e}")

# Sample queries to rotate through
SAMPLE_QUERIES = [
    "SELECT COUNT(*), AVG(value) FROM test_table WHERE value > 100",
    "SELECT a.id, a.name, b.value FROM test_table a JOIN test_table b ON a.value < b.value WHERE a.id < 100 AND b.id < 100 LIMIT 100",
    "SELECT name, MAX(value) FROM test_table GROUP BY name LIMIT 100",
    "SELECT id, name, value FROM test_table WHERE id % 10 = 0 ORDER BY value DESC LIMIT 100",
    "SELECT EXTRACT(HOUR FROM created_at) as hour, COUNT(*), AVG(value) FROM test_table GROUP BY EXTRACT(HOUR FROM created_at) ORDER BY hour"
]

@app.route('/')
def index():
    # Containers should already be initialized at startup
    if not db_manager.containers_started or not db_manager.data_loaded:
        try:
            # If for some reason containers aren't running, try to start them
            db_manager.ensure_containers_running()
            db_manager.load_test_data()
        except Exception as e:
            return render_template('error.html', error=str(e))
    
    # Generate a user ID if not already in session
    # if 'user_id' not in session:
    #     session['user_id'] = f"user_{uuid.uuid4().hex[:8]}"
    # user_id = session['user_id']
    user_id = f"user_{random.randint(1, 10000)}"

    # Use Split.io to determine which database to use
    db_choice = split_client.get_treatment(user_id, "db_performance_comparison")

    if db_choice not in ["postgres", "mariadb"]:
        db_choice = "postgres"  # Default if Split.io fails
    
    # Pick a query - either from request or randomly
    query = request.args.get('query')
    if not query:
        query = random.choice(SAMPLE_QUERIES)
    
    # Run the query
    try:
        result = db_manager.run_query(query, db_choice)
        
        # Track metrics with Split.io
        split_client.track(user_id, "user", "query_execution", result["execution_time"], {"query": query, "database": db_choice})
        
        # Create a record for the execution history
        execution = {
            "database": db_choice,
            "query": query,
            "execution_time": result["execution_time"],
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        
        # Store history in session
        if 'history' not in session:
            session['history'] = []
        
        history = session.get('history', [])
        history.append(execution)
        session['history'] = history[-10:]  # Keep only the last 10 executions
        
        return render_template('results.html', 
                              user_id=user_id,
                              db_choice=db_choice,
                              query=query,
                              execution_time=result["execution_time"],
                              results=result["results"],
                              column_names=result["column_names"],
                              history=session['history'],
                              sample_queries=SAMPLE_QUERIES)
    except Exception as e:
        return render_template('error.html', error=str(e))

@app.route('/cleanup')
def cleanup():
    try:
        split_client.destroy()
        db_manager.cleanup()
        return "Cleanup successful. Containers stopped and removed."
    except Exception as e:
        return f"Error during cleanup: {str(e)}"

def signal_handler(sig, frame):
    """Handle termination signals and clean up resources"""
    print(f"\nReceived signal {sig}. Cleaning up resources before exit...")
    try:
        split_client.destroy()
        print("Split.io client destroyed successfully")
    except Exception as e:
        print(f"Error destroying Split.io client: {e}")
    
    try:
        db_manager.cleanup()
        print("Containers cleaned up successfully")
    except Exception as e:
        print(f"Error during container cleanup: {e}")
    
    print("Cleanup complete, exiting now")
    sys.exit(0)

# Register the shutdown functions
def register_shutdown_handlers():
    # Register for SIGINT (Ctrl+C) and SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Register cleanup with atexit as a backup
    atexit.register(lambda: db_manager.cleanup())
    atexit.register(lambda: split_client.destroy())
    
    # Note: SIGKILL (kill -9) cannot be caught and handled

if __name__ == "__main__":
    register_shutdown_handlers()
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    except Exception as e:
        print(f"Error running Flask app: {e}")
        # The signal handler or atexit will handle cleanup

# Database Performance Comparison Web App

This web application compares the performance of PostgreSQL and MariaDB by running identical queries and measuring execution times. It uses Harness FME feature flags to dynamically determine which database to use for each request.

## Features

- Web interface that displays query results and execution times
- Dynamic database selection via Harness FME feature flags
- Sample queries to test different database operations
- Execution history tracking
- Container management for PostgreSQL and MariaDB

## Prerequisites

- Docker installed and running
- Python 3.6+
- Harness FME account for feature flag management (or use localhost mode for testing)

## Installation

1. Clone or download this repository
2. Install required Python dependencies:

```
pip install -r requirements.txt
```

3. Create a `.env` file based on the `.env.example` template:

```
cp .env.example .env
```

4. Edit the `.env` file to add your Harness FME API key and a secure Flask secret key

## Harness FME Configuration

1. Create a Harness FME account if you don't have one
2. Create a feature flag named `db_performance_comparison` with two treatments: `postgres` and `mariadb`
3. Configure your targeting rules as desired (e.g., 50/50 split, geolocation-based, etc.)
4. Copy your API key to the `.env` file

## Running the Application

Start the web server:

```
python app.py
```

Access the application at: http://localhost:5000

## How It Works

1. Each time a user loads the page, the application:
   - Ensures PostgreSQL and MariaDB containers are running
   - Loads test data if needed
   - Consults the Harness FME feature flag to determine which database to query
   - Executes the query on the selected database
   - Displays results and execution time in a user-friendly interface
   - Tracks query execution history

2. Users can:
   - Run new queries by reloading the page
   - Select from sample queries
   - View execution history
   - Clean up containers when finished

## Load Testing

The application includes a load testing script (`load_tester.py`) that can simulate multiple concurrent users accessing the web application. This is useful for generating traffic to the feature flag system and comparing database performance under load.

### Prerequisites

Install the required dependencies for load testing:

```bash
pip install selenium webdriver-manager
```

You'll need Chrome browser installed for the test script to work.

### Running Load Tests

Basic usage with default settings (5 concurrent sessions, 60 seconds duration):

```bash
python load_tester.py
```

Advanced usage with more options:

```bash
python load_tester.py --sessions 10 --duration 60 --auto-refresh
```

### Command-line Options

- `--url` - Base URL of the web app (default: http://localhost:5000)
- `--sessions` - Number of concurrent browser sessions (default: 5)
- `--duration` - How long each session should run in seconds (default: 60)
- `--auto-refresh` - Use the application's built-in auto-refresh feature
- `--refresh-interval` - Seconds between refreshes for manual mode (default: 5)
- `--queries` - Specific queries to distribute across sessions

Example with specific queries:

```bash
python load_tester.py --sessions 20 --queries "SELECT COUNT(*) FROM test_table" "SELECT * FROM test_table LIMIT 10"
```

## Clean Up

To stop and remove the Docker containers, visit: http://localhost:5000/cleanup

Or simply stop the Flask server with Ctrl+C (the application will clean up containers automatically)

#!/usr/bin/env python3
import argparse
import time
import uuid
import threading
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from concurrent.futures import ThreadPoolExecutor


class BrowserSession:
    """Manages a headless browser session accessing the DB performance app"""
    def __init__(self, base_url, session_id=None, auto_refresh=False, query=None):
        """Initialize a browser session
        
        Args:
            base_url: Base URL of the web application
            session_id: Unique identifier for this session (used for tracking)
            auto_refresh: Whether to use the app's auto-refresh feature
            query: Optional specific query to test
        """
        self.base_url = base_url
        self.session_id = session_id or f"load-test-{uuid.uuid4().hex[:8]}"
        self.auto_refresh = auto_refresh
        self.query = query
        self.browser = None
        self.stop_event = threading.Event()
        
    def start(self, duration_seconds=60, manual_refresh_interval=5):
        """Start the browser session
        
        Args:
            duration_seconds: How long to run this session
            manual_refresh_interval: Seconds between manual refreshes (if auto_refresh=False)
        """
        try:
            print(f"Starting browser session {self.session_id}")
            
            # Setup Chrome in headless mode
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument(f"--user-agent=LoadTest/{self.session_id}")
            
            # Initialize the browser
            try:
                # First try the simple approach without webdriver_manager
                self.browser = webdriver.Chrome(options=chrome_options)
            except Exception as e:
                print(f"Session {self.session_id}: Using fallback ChromeDriver initialization: {e}")
                try:
                    # Try with explicit service but no manager
                    service = Service()
                    self.browser = webdriver.Chrome(service=service, options=chrome_options)
                except Exception as e2:
                    print(f"Session {self.session_id}: Chrome initialization error: {e2}")
                    raise
            
            # Construct URL with optional query
            url = self.base_url
            if self.query:
                url = f"{self.base_url}?query={self.query}"
            
            # Load the initial page
            self.browser.get(url)
            print(f"Session {self.session_id}: Loaded initial page")
            
            # Start auto-refresh if requested
            if self.auto_refresh:
                try:
                    # Find and click the auto-refresh button
                    start_button = self.browser.find_element("id", "startAutoRefresh")
                    start_button.click()
                    print(f"Session {self.session_id}: Activated auto-refresh")
                except Exception as e:
                    print(f"Session {self.session_id}: Could not activate auto-refresh: {e}")
            
            # Run for specified duration
            start_time = time.time()
            refresh_count = 0
            
            while (time.time() - start_time) < duration_seconds:
                # Check if we've been asked to stop
                if self.stop_event.is_set():
                    break
                    
                # If not using auto-refresh, manually refresh
                if not self.auto_refresh:
                    if (time.time() - start_time) > manual_refresh_interval * (refresh_count + 1):
                        self.browser.refresh()
                        refresh_count += 1
                        print(f"Session {self.session_id}: Manual refresh #{refresh_count}")
                
                # Sleep briefly to avoid hammering the CPU
                time.sleep(0.5)
                
        except Exception as e:
            print(f"Session {self.session_id}: Error: {e}")
        finally:
            self.cleanup()
                
    def cleanup(self):
        """Clean up browser resources"""
        if self.browser:
            try:
                # If using auto-refresh, try to stop it first
                if self.auto_refresh:
                    try:
                        stop_button = self.browser.find_element("id", "stopAutoRefresh")
                        stop_button.click()
                        print(f"Session {self.session_id}: Deactivated auto-refresh")
                    except:
                        pass  # Button might not be accessible, that's OK
                
                # Close the browser
                self.browser.quit()
                print(f"Session {self.session_id}: Browser closed")
            except:
                pass
            self.browser = None
            
    def stop(self):
        """Signal this session to stop"""
        self.stop_event.set()


def run_browser_session(args):
    """Function to run in a thread pool to manage a single browser session"""
    session_id, base_url, duration, auto_refresh, refresh_interval, query = args
    session = BrowserSession(
        base_url=base_url,
        session_id=session_id,
        auto_refresh=auto_refresh,
        query=query
    )
    session.start(duration_seconds=duration, manual_refresh_interval=refresh_interval)
    return session_id


def main():
    parser = argparse.ArgumentParser(
        description='Load test for DB performance comparison app'
    )
    parser.add_argument(
        '--url', 
        default='http://localhost:5000',
        help='Base URL of the web application (default: http://localhost:5000)'
    )
    parser.add_argument(
        '--sessions', 
        type=int, 
        default=5,
        help='Number of browser sessions to run concurrently (default: 5)'
    )
    parser.add_argument(
        '--duration', 
        type=int, 
        default=60,
        help='Duration in seconds for each session (default: 60)'
    )
    parser.add_argument(
        '--auto-refresh', 
        action='store_true',
        help='Use the application\'s auto-refresh feature (default: manual refresh)'
    )
    parser.add_argument(
        '--refresh-interval', 
        type=int, 
        default=5,
        help='Refresh interval in seconds for manual refresh (default: 5)'
    )
    parser.add_argument(
        '--queries',
        nargs='+',
        help='Optional specific queries to test (will be distributed across sessions)'
    )
    
    args = parser.parse_args()
    
    print(f"Starting load test with {args.sessions} concurrent sessions")
    print(f"Target URL: {args.url}")
    print(f"Duration per session: {args.duration} seconds")
    print(f"Auto-refresh: {'Enabled' if args.auto_refresh else 'Disabled'}")
    if not args.auto_refresh:
        print(f"Manual refresh interval: {args.refresh_interval} seconds")
    
    # Generate session arguments
    session_args = []
    for i in range(args.sessions):
        session_id = f"session-{i+1}"
        
        # Assign a specific query if provided
        query = None
        if args.queries:
            query = args.queries[i % len(args.queries)]
        
        session_args.append((
            session_id,
            args.url,
            args.duration,
            args.auto_refresh,
            args.refresh_interval,
            query
        ))
    
    # Run browser sessions in parallel using a thread pool
    start_time = time.time()
    completed = 0
    
    with ThreadPoolExecutor(max_workers=args.sessions) as executor:
        future_to_session = {
            executor.submit(run_browser_session, arg): arg[0]
            for arg in session_args
        }
        
        for future in future_to_session:
            try:
                session_id = future.result()
                completed += 1
                print(f"Session {session_id} completed")
            except Exception as e:
                print(f"Session error: {e}")
    
    total_time = time.time() - start_time
    print(f"\nLoad test completed in {total_time:.1f} seconds")
    print(f"{completed}/{args.sessions} sessions completed successfully")
    

if __name__ == "__main__":
    main()

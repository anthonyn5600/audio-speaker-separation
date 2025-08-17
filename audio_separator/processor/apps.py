from django.apps import AppConfig
import signal
import sys
import logging


class ProcessorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "processor"
    
    def ready(self):
        """Called when the app is ready. Set up signal handlers."""
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown"""
        logger = logging.getLogger(__name__)
        
        def signal_handler(signum, frame):
            """Handle SIGINT (Ctrl+C) and SIGTERM signals"""
            signal_name = 'SIGINT' if signum == signal.SIGINT else 'SIGTERM'
            logger.info(f"Received {signal_name}, cancelling all running jobs and shutting down gracefully...")
            
            try:
                # Import here to avoid circular imports
                from .services import job_statuses, job_cancellations, job_threads, audio_service
                
                # Cancel all running jobs
                running_jobs = [job_id for job_id, status in job_statuses.items() 
                               if status.get('status') == 'processing']
                
                if running_jobs:
                    logger.info(f"Cancelling {len(running_jobs)} running jobs: {running_jobs}")
                    
                    for job_id in running_jobs:
                        try:
                            audio_service.cancel_job(job_id)
                            logger.info(f"Cancelled job {job_id}")
                        except Exception as e:
                            logger.error(f"Error cancelling job {job_id}: {e}")
                    
                    # Wait a moment for jobs to clean up
                    import time
                    time.sleep(1)
                
                logger.info("All jobs cancelled. Shutting down.")
                
            except Exception as e:
                logger.error(f"Error during signal handling: {e}")
            
            # Exit gracefully
            sys.exit(0)
        
        # Register signal handlers for both SIGINT (Ctrl+C) and SIGTERM
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            logger.info("Signal handlers registered for SIGINT and SIGTERM")
        except ValueError as e:
            # On Windows, signal handling might be limited
            logger.warning(f"Could not register all signal handlers: {e}")
            try:
                signal.signal(signal.SIGINT, signal_handler)
                logger.info("Signal handler registered for SIGINT only")
            except Exception as e2:
                logger.error(f"Could not register SIGINT handler: {e2}")

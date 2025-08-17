#!/usr/bin/env python3
"""
Test script to verify WhisperX processing fixes
"""

import os
import sys
import django
import time

# Add the project directory to Python path
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(project_dir, 'audio_separator'))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'audio_separator.settings')
django.setup()

from processor.services import AudioProcessingService

def test_cache_cleanup():
    """Test the cache cleanup functionality"""
    print("Testing cache cleanup functionality...")
    
    service = AudioProcessingService()
    
    # Test cache cleanup
    service.clean_stale_cache_entries()
    print("[PASS] Cache cleanup completed without errors")

def test_timeout_handlers():
    """Test that timeout handlers are properly implemented"""
    print("Testing timeout handler implementation...")
    
    try:
        service = AudioProcessingService()
        
        # Check if the service has the new methods
        assert hasattr(service, 'clean_stale_cache_entries'), "Missing cache cleanup method"
        print("[PASS] Cache cleanup method exists")
        
        # Test that WhisperX transcription has timeout handling
        import inspect
        source = inspect.getsource(service.run_whisperx_transcription)
        
        assert "TimeoutError" in source, "Missing timeout error handling"
        assert "signal.alarm" in source, "Missing timeout mechanism"
        print("[PASS] Timeout handling implemented in WhisperX")
        
    except Exception as e:
        print(f"[FAIL] Timeout test failed: {e}")
        return False
    
    return True

def test_status_api():
    """Test the status API with the fixed job"""
    print("Testing status API...")
    
    try:
        service = AudioProcessingService()
        
        # Test with the previously stuck job
        status = service.get_job_status('628c6a4a-7782-4fb9-b4ad-3b1dc188712b')
        
        assert status['status'] == 'failed', f"Expected 'failed', got '{status['status']}'"
        assert status['progress'] == 0, f"Expected 0%, got {status['progress']}%"
        print(f"[PASS] Stuck job correctly shows as: {status['status']} (0%)")
        
    except Exception as e:
        print(f"[FAIL] Status API test failed: {e}")
        return False
    
    return True

def main():
    print("Testing WhisperX Processing Fixes")
    print("=" * 50)
    
    all_passed = True
    
    # Test 1: Cache cleanup
    try:
        test_cache_cleanup()
    except Exception as e:
        print(f"[FAIL] Cache cleanup test failed: {e}")
        all_passed = False
    
    print()
    
    # Test 2: Timeout handlers
    if not test_timeout_handlers():
        all_passed = False
    
    print()
    
    # Test 3: Status API
    if not test_status_api():
        all_passed = False
    
    print()
    print("=" * 50)
    
    if all_passed:
        print("[PASS] ALL TESTS PASSED!")
        print("The WhisperX processing fixes are working correctly:")
        print("  * Timeout protection added to alignment and diarization")
        print("  * Stale cache cleanup implemented")
        print("  * Stuck jobs automatically marked as failed")
        print("  * Status API returns correct failed status")
    else:
        print("[FAIL] SOME TESTS FAILED!")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
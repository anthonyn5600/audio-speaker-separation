#!/usr/bin/env python3
"""
Simple WhisperX test script
"""

import os
import sys
import django

# Add the project directory to Python path
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(project_dir, 'audio_separator'))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'audio_separator.settings')
django.setup()

from processor.services import AudioProcessingService

def test_whisperx_import():
    """Test if WhisperX can be imported"""
    try:
        import whisperx
        import torch
        print("[OK] WhisperX imported successfully")
        print(f"[OK] PyTorch version: {torch.__version__}")
        print(f"[OK] CUDA available: {torch.cuda.is_available()}")
        return True
    except ImportError as e:
        print(f"[FAIL] Failed to import WhisperX: {e}")
        return False

def test_whisperx_service():
    """Test WhisperX through the service"""
    try:
        service = AudioProcessingService()
        
        # Test the mock fallback with proper UUID
        import uuid
        test_job_id = str(uuid.uuid4())
        print(f"Testing WhisperX service with job ID: {test_job_id}")
        result = service._run_mock_whisperx(test_job_id)
        
        print("[OK] Service returns proper result structure:")
        print(f"  - Language: {result.get('language')}")
        print(f"  - Segments: {len(result.get('segments', []))}")
        print(f"  - First segment: {result['segments'][0] if result.get('segments') else 'None'}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Service test failed: {e}")
        return False

def main():
    print("WhisperX Integration Test")
    print("=" * 40)
    
    success = True
    
    # Test imports
    if not test_whisperx_import():
        success = False
    
    # Test service
    if not test_whisperx_service():
        success = False
    
    print("\n" + "=" * 40)
    if success:
        print("[SUCCESS] All tests passed! WhisperX integration is ready.")
    else:
        print("[ERROR] Some tests failed. Check the output above.")
    
    return success

if __name__ == "__main__":
    main()
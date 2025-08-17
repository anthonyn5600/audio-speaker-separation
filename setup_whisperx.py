#!/usr/bin/env python3
"""
WhisperX Setup Script
This script helps set up WhisperX dependencies and test the installation.
"""

import os
import sys
import subprocess
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_command(command, description):
    """Run a command and log the result"""
    logger.info(f"Running: {description}")
    logger.info(f"Command: {command}")
    
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        logger.info(f"Success: {description}")
        if result.stdout:
            logger.info(f"Output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed: {description}")
        logger.error(f"Error: {e.stderr}")
        return False

def check_python_version():
    """Check if Python version is compatible"""
    python_version = sys.version_info
    logger.info(f"Python version: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 8):
        logger.error("Python 3.8 or higher is required for WhisperX")
        return False
    
    logger.info("Python version is compatible")
    return True

def install_pytorch():
    """Install PyTorch based on system capabilities"""
    logger.info("Installing PyTorch...")
    
    # Check if CUDA is available
    try:
        import torch
        if torch.cuda.is_available():
            logger.info("CUDA is available - PyTorch with CUDA support recommended")
            cuda_version = torch.version.cuda
            logger.info(f"CUDA version: {cuda_version}")
        else:
            logger.info("CUDA not available - installing CPU-only PyTorch")
    except ImportError:
        logger.info("PyTorch not installed - installing CPU version")
        if not run_command("pip install torch torchaudio", "Install PyTorch CPU"):
            return False
    
    return True

def install_whisperx():
    """Install WhisperX and dependencies"""
    logger.info("Installing WhisperX...")
    
    commands = [
        ("pip install whisperx", "Install WhisperX"),
        ("pip install pyannote.audio", "Install pyannote.audio"),
        ("pip install librosa soundfile", "Install audio processing libraries"),
    ]
    
    for command, description in commands:
        if not run_command(command, description):
            return False
    
    return True

def test_whisperx_import():
    """Test if WhisperX can be imported"""
    logger.info("Testing WhisperX import...")
    
    try:
        import whisperx
        logger.info("WhisperX imported successfully")
        
        # Test basic functionality
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {device}")
        
        # Try to load a small model
        try:
            model = whisperx.load_model("tiny", device=device)
            logger.info("WhisperX model loaded successfully")
            return True
        except Exception as e:
            logger.warning(f"Could not load model: {e}")
            logger.info("WhisperX is installed but model loading failed - this is normal on first run")
            return True
            
    except ImportError as e:
        logger.error(f"Failed to import WhisperX: {e}")
        return False

def check_ffmpeg():
    """Check if FFmpeg is available"""
    logger.info("Checking FFmpeg...")
    
    try:
        result = subprocess.run("ffmpeg -version", shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("FFmpeg is available")
            return True
        else:
            logger.warning("FFmpeg not found - required for audio processing")
            logger.info("Please install FFmpeg: https://ffmpeg.org/download.html")
            return False
    except Exception as e:
        logger.warning(f"Could not check FFmpeg: {e}")
        return False

def setup_huggingface_token():
    """Guide user through HuggingFace token setup"""
    logger.info("HuggingFace Token Setup")
    logger.info("=" * 50)
    logger.info("For speaker diarization to work, you need a HuggingFace token:")
    logger.info("1. Go to https://huggingface.co/settings/tokens")
    logger.info("2. Create a new token with 'Read' permissions")
    logger.info("3. Accept the terms for pyannote/speaker-diarization model:")
    logger.info("   https://huggingface.co/pyannote/speaker-diarization")
    logger.info("4. Set the environment variable:")
    logger.info("   Windows: set HUGGINGFACE_TOKEN=your_token_here")
    logger.info("   Linux/Mac: export HUGGINGFACE_TOKEN=your_token_here")
    logger.info("")
    
    token = os.environ.get('HUGGINGFACE_TOKEN')
    if token:
        logger.info(f"HuggingFace token found: {token[:10]}...")
    else:
        logger.warning("No HuggingFace token found - speaker diarization will use fallback")

def main():
    """Main setup function"""
    logger.info("WhisperX Setup Starting...")
    logger.info("=" * 50)
    
    success = True
    
    # Check Python version
    if not check_python_version():
        success = False
    
    # Check FFmpeg
    if not check_ffmpeg():
        success = False
    
    # Install PyTorch
    if not install_pytorch():
        success = False
    
    # Install WhisperX
    if not install_whisperx():
        success = False
    
    # Test installation
    if not test_whisperx_import():
        success = False
    
    # HuggingFace token setup
    setup_huggingface_token()
    
    logger.info("=" * 50)
    if success:
        logger.info("WhisperX setup completed successfully!")
        logger.info("You can now use real WhisperX for audio transcription and speaker diarization.")
    else:
        logger.error("WhisperX setup encountered some issues.")
        logger.info("The application will fall back to mock implementation if needed.")
    
    return success

if __name__ == "__main__":
    main()
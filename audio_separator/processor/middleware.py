"""
Security middleware for rate limiting and additional protections
"""

import time
import hashlib
from django.http import JsonResponse
from django.core.cache import cache
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class RateLimitMiddleware:
    """Simple rate limiting middleware"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Rate limits per endpoint (requests per minute)
        self.rate_limits = {
            '/api/upload/': 5,  # 5 uploads per minute
            '/api/status/': 60,  # 60 status checks per minute
            '/api/update-speaker/': 20,  # 20 speaker updates per minute
        }
    
    def __call__(self, request):
        # Check rate limits before processing request
        if self.is_rate_limited(request):
            logger.warning(f"Rate limit exceeded for {request.META.get('REMOTE_ADDR')} on {request.path}")
            return JsonResponse({
                'error': 'Rate limit exceeded. Please try again later.',
                'status': 'rate_limited'
            }, status=429)
        
        response = self.get_response(request)
        return response
    
    def is_rate_limited(self, request):
        """Check if request should be rate limited"""
        
        # Skip rate limiting for non-API endpoints
        if not request.path.startswith('/api/'):
            return False
        
        # Get client identifier (IP + User Agent hash for some uniqueness)
        client_ip = self.get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        client_id = hashlib.md5(f"{client_ip}:{user_agent}".encode()).hexdigest()
        
        # Get rate limit for this endpoint
        rate_limit = None
        for endpoint, limit in self.rate_limits.items():
            if request.path.startswith(endpoint):
                rate_limit = limit
                break
        
        if not rate_limit:
            return False
        
        # Check rate limit using cache
        cache_key = f"rate_limit:{client_id}:{request.path}"
        current_time = int(time.time())
        window_start = current_time - 60  # 1-minute window
        
        # Get request timestamps for this client
        requests = cache.get(cache_key, [])
        
        # Remove old requests outside the window
        requests = [req_time for req_time in requests if req_time > window_start]
        
        # Check if rate limit exceeded
        if len(requests) >= rate_limit:
            return True
        
        # Add current request
        requests.append(current_time)
        cache.set(cache_key, requests, 60)  # Cache for 1 minute
        
        return False
    
    def get_client_ip(self, request):
        """Get client IP address handling proxy headers"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

class SecurityHeadersMiddleware:
    """Add security headers to all responses"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Add security headers
        if not settings.DEBUG:
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Basic CSP for audio application
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "media-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self';"
        )
        response['Content-Security-Policy'] = csp
        
        return response

class FileUploadSecurityMiddleware:
    """Additional security for file uploads"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.max_uploads_per_hour = 10  # Max uploads per IP per hour
    
    def __call__(self, request):
        # Additional security for upload endpoint
        if request.path == '/api/upload/' and request.method == 'POST':
            if not self.check_upload_limits(request):
                logger.warning(f"Upload limit exceeded for {request.META.get('REMOTE_ADDR')}")
                return JsonResponse({
                    'error': 'Upload limit exceeded. Maximum 10 uploads per hour.',
                    'status': 'upload_limit_exceeded'
                }, status=429)
        
        response = self.get_response(request)
        return response
    
    def check_upload_limits(self, request):
        """Check hourly upload limits"""
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        cache_key = f"upload_count:{client_ip}"
        
        current_count = cache.get(cache_key, 0)
        if current_count >= self.max_uploads_per_hour:
            return False
        
        # Increment counter
        cache.set(cache_key, current_count + 1, 3600)  # 1 hour expiry
        return True
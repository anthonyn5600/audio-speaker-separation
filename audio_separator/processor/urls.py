from django.urls import path
from . import views

app_name = 'processor'

urlpatterns = [
    # Main pages
    path('', views.index, name='index'),
    path('status/<uuid:job_id>/', views.status, name='status'),
    path('results/<uuid:job_id>/', views.results, name='results'),
    
    # API endpoints
    path('api/upload/', views.upload_file, name='upload_file'),
    path('api/status/<uuid:job_id>/', views.status_api, name='status_api'),
    path('api/cancel/<uuid:job_id>/', views.cancel_job_view, name='cancel_job'),
    path('api/update-speaker/<uuid:job_id>/', views.update_speaker_name, name='update_speaker_name'),
    
    # Audio serving and downloads
    path('audio/<uuid:job_id>/<str:speaker_id>/', views.serve_audio, name='serve_audio'),
    path('download/<uuid:job_id>/<str:speaker_id>/', views.download_audio, name='download_audio'),
]

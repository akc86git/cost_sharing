"""Маршруты сервиса «Разделение затрат» (страницы сайта + JSON API)."""
from django.urls import path

from . import api, views

urlpatterns = [
    path('', views.index, name='index'),
    path('people/add/', views.person_add, name='person_add'),
    path('events/add/', views.event_add, name='event_add'),
    path('purchases/add/', views.purchase_add, name='purchase_add'),
    path('purchases/', views.purchases_list, name='purchases'),
    path('purchases/<int:purchase_id>/', views.purchase_detail, name='purchase_detail'),
    path('report/', views.report, name='report'),
    path('report/<int:event_id>/export/xlsx/', views.report_export_xlsx, name='report_export_xlsx'),
    path('report/<int:event_id>/export/pdf/', views.report_export_pdf, name='report_export_pdf'),

    path('api/people/', api.api_people, name='api_people'),
    path('api/events/', api.api_events, name='api_events'),
    path('api/purchases/', api.api_purchases, name='api_purchases'),
    path('api/purchases/<int:purchase_id>/', api.api_purchase_detail, name='api_purchase_detail'),
    path('api/events/<int:event_id>/report/', api.api_event_report, name='api_event_report'),
]

from django.urls import path
from . import views

urlpatterns = [
    # Home
    path('', views.home, name='index'),
    
    # About
    path('about/', views.about, name='about'),
    
    # Rooms
    path('room/', views.room, name='room'),
    path('rooms/', views.room_list, name='room_list'),
    path('room/<int:room_id>/', views.room_detail, name='room_detail'),
    
    # Amenities
    path('amenities/', views.amenities, name='amenities'),
    
    # Booking
    path('booking/', views.booking_view, name='booking'),
    path('booking-confirmation/<int:booking_id>/', views.booking_confirmation, name='booking_confirmation'),

    # Payments
    path('payments/<int:booking_id>/', views.payment_page, name='payment_page'),
    path('payments/success/<int:booking_id>/', views.payment_success, name='payment_success'),
    path('payments/failed/<int:booking_id>/', views.payment_failed, name='payment_failed'),
    path('payments/invoice/<int:booking_id>/', views.invoice_pdf, name='invoice_pdf'),
    path('payments/stripe/create-intent/', views.stripe_create_intent, name='stripe_create_intent'),
    path('payments/stripe/confirm/', views.stripe_confirm, name='stripe_confirm'),
    path('payments/stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('payments/paypal/create-order/', views.paypal_create_order, name='paypal_create_order'),
    path('payments/paypal/return/', views.paypal_return, name='paypal_return'),
    path('payments/paypal/cancel/', views.paypal_cancel, name='paypal_cancel'),
    path('payments/mpesa/stk-push/', views.mpesa_stk_push, name='mpesa_stk_push'),
    
    # Authentication
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    
    # Contact
    path('contact/', views.contact, name='contact'),
    
    # Subscribe
    path('subscribe/', views.subscribe, name='subscribe'),
]

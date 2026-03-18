from django.urls import path
from django.views.i18n import set_language
from . import views
from . import api_views

urlpatterns = [
    path('set-language/', set_language, name='set_language'),
    path('health/', api_views.health_check, name='health_check'),
    path('api/auth/me/', api_views.jwt_me, name='jwt_me'),
    # Home
    path('', views.home, name='index'),
    path('search/', views.search, name='search'),
    
    # About
    path('about/', views.about, name='about'),
    
    # Rooms
    path('room/', views.room, name='room'),
    path('rooms/', views.room_list, name='room_list'),
    path('room/<int:room_id>/', views.room_detail, name='room_detail'),
    path('hotels/', views.hotel_list, name='hotel_list'),
    path('hotels/<int:hotel_id>/', views.hotel_detail, name='hotel_detail'),
    
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
    path('payments/mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    
    # Authentication
    path('login/', views.login_view, name='login'),
    path('auth/google/', views.google_login, name='google_login'),
    path('auth/google/callback/', views.google_callback, name='google_callback'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('password-reset/', views.password_reset_request, name='password_reset'),
    path('password-reset/verify/', views.password_reset_verify, name='password_reset_verify'),
    path('my-bookings/', views.my_bookings_view, name='my_bookings'),
    path('reviews/submit/<int:booking_id>/', views.submit_review, name='submit_review'),
    path('owner/dashboard/', views.owner_dashboard, name='owner_dashboard'),
    path('owner/hotels/add/', views.owner_add_hotel, name='owner_add_hotel'),
    path('owner/rooms/add/', views.owner_add_room, name='owner_add_room'),
    path('owner/hotel-apply/', views.hotel_partner_apply, name='hotel_partner_apply'),
    path('owner/hotel-application/', views.hotel_application_status, name='hotel_application_status'),
    path('admin-users/', views.admin_users_view, name='admin_users'),
    path('admin-users/<int:user_id>/', views.admin_user_detail, name='admin_user_detail'),
    path('admin-users/<int:user_id>/edit/', views.admin_user_edit, name='admin_user_edit'),
    path('admin-users/<int:user_id>/toggle-active/', views.admin_user_toggle_active, name='admin_user_toggle_active'),
    path('admin-hotels/', views.admin_hotels_view, name='admin_hotels'),
    path('admin-hotels/<int:hotel_id>/', views.admin_hotel_detail, name='admin_hotel_detail'),
    path('admin-hotels/<int:hotel_id>/edit/', views.admin_hotel_edit, name='admin_hotel_edit'),
    path('admin-hotels/<int:hotel_id>/disable/', views.admin_disable_hotel, name='admin_disable_hotel'),
    path('admin-payments/', views.admin_payments_view, name='admin_payments'),
    path('admin-booked-rooms/', views.admin_booked_rooms_view, name='admin_booked_rooms'),
    path('admin-rooms/', views.admin_rooms_view, name='admin_rooms'),
    path('admin-rooms/<int:room_id>/', views.admin_room_detail, name='admin_room_detail'),
    path('admin-rooms/<int:room_id>/edit/', views.admin_room_edit, name='admin_room_edit'),
    path('admin-rooms/<int:room_id>/disable/', views.admin_disable_room, name='admin_disable_room'),
    path('admin-hotel-applications/', views.admin_hotel_applications_view, name='admin_hotel_applications'),
    path('admin-hotel-applications/<int:application_id>/', views.admin_hotel_application_detail, name='admin_hotel_application_detail'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-rooms/<int:room_id>/approve/', views.admin_approve_room, name='admin_approve_room'),
    path('admin-rooms/<int:room_id>/reject/', views.admin_reject_room, name='admin_reject_room'),
    
    # Contact
    path('contact/', views.contact, name='contact'),
    
    # Subscribe
    path('subscribe/', views.subscribe, name='subscribe'),
]

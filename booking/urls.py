from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.i18n import set_language
from . import views

urlpatterns = [
    path('set-language/', set_language, name='set_language'),
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
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(template_name='registration/password_reset_form.html'),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'),
        name='password_reset_complete',
    ),
    path('my-bookings/', views.my_bookings_view, name='my_bookings'),
    path('reviews/submit/<int:booking_id>/', views.submit_review, name='submit_review'),
    path('owner/dashboard/', views.owner_dashboard, name='owner_dashboard'),
    path('owner/hotels/add/', views.owner_add_hotel, name='owner_add_hotel'),
    path('owner/rooms/add/', views.owner_add_room, name='owner_add_room'),
    path('owner/hotel-apply/', views.hotel_partner_apply, name='hotel_partner_apply'),
    path('owner/hotel-application/', views.hotel_application_status, name='hotel_application_status'),
    path('admin-users/', views.admin_users_view, name='admin_users'),
    path('admin-payments/', views.admin_payments_view, name='admin_payments'),
    path('admin-booked-rooms/', views.admin_booked_rooms_view, name='admin_booked_rooms'),
    path('admin-rooms/', views.admin_rooms_view, name='admin_rooms'),
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

(function ($) {
    "use strict";
    
    // Initiate the wowjs animation library
    new WOW().init();
    
    // Initiate responsive menu
    var $menuToggle = $('.mobile-menu-btn');
    var $mobileMenu = $('#mobile-menu-panel');
    var $desktopMenu = $('#header .top-menu').first();

    function setMobileMenuState(isOpen) {
        if (!$mobileMenu.length || !$menuToggle.length) {
            return;
        }

        $mobileMenu.toggleClass('is-open', isOpen).attr('aria-hidden', String(!isOpen));
        $menuToggle.attr('aria-expanded', String(isOpen));
        $menuToggle
            .find('i')
            .toggleClass('fa-bars', !isOpen)
            .toggleClass('fa-times', isOpen);
        $('body').toggleClass('mobile-nav-open', isOpen);
    }

    if ($mobileMenu.length) {
        $mobileMenu.find('.dropdown').removeClass('show');
        $mobileMenu.find('.dropdown-menu').removeClass('show');
    }

    $menuToggle.on('click', function () {
        setMobileMenuState(!$mobileMenu.hasClass('is-open'));
    });

    $(document).on('click', '.mobile-menu-close', function () {
        setMobileMenuState(false);
    });

    $(document).on('click', '#mobile-menu-panel a', function () {
        if (!$(this).hasClass('dropdown-toggle')) {
            setMobileMenuState(false);
        }
    });

    $(document).on('click', '#mobile-menu-panel .dropdown-toggle', function (event) {
        event.preventDefault();
        $(this).closest('.dropdown').toggleClass('show');
    });

    $(document).on('keyup', function (event) {
        if (event.key === 'Escape') {
            setMobileMenuState(false);
        }
    });

    $(window).on('resize', function () {
        if (window.innerWidth >= 1200) {
            setMobileMenuState(false);
        }
    });
    
    // Back to top button
    $(window).scroll(function () {
        if ($(this).scrollTop() > 100) {
            $('.back-to-top').fadeIn('slow');
        } else {
            $('.back-to-top').fadeOut('slow');
        }
    });
    $('.back-to-top').click(function () {
        $('html, body').animate({scrollTop: 0}, 1500, 'easeInOutExpo');
        return false;
    });
    
    // Date and time picker
    $('#date-1, #date-2, #date-3, #date-4').datetimepicker({
        format: 'L'
    });
    $('#time-1, #time-2').datetimepicker({
        format: 'LT'
    });
    
    //Portfolio modal slider
    $('.port-slider').delay(10000);
    $('.port-slider').slick({
        autoplay: true,
        slidesToShow: 1,
        slidesToScroll: 1,
        arrows: false,
        fade: true,
        asNavFor: '.port-slider-nav'
    });
    $('.port-slider-nav').slick({
        autoplay: true,
        slidesToShow: 5,
        slidesToScroll: 1,
        asNavFor: '.port-slider',
        arrows: false,
        dots: false,
        centerMode: true,
        focusOnSelect: true
    });
    
    $('#popover-content-download').hide();
    $("[data-toggle=popover]").each(function (e) {
        $(this).popover({
            html: true,
            content: function () {
                var id = $(this).attr('id')
                return $('#popover-content-' + id).html();
            }
        });

    });
})(jQuery);


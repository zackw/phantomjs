# -*- coding: utf-8 -*-

__author__ = 'Jason Gowan'

# Ported CookieTest.java ghostdriver test from java to python.

import time
from selenium.common.exceptions import WebDriverException

def go_to_page(d, path):
    d.get(T.http_base + path)

@T.test
def getting_all_cookies(d):
    go_to_page(d, '/cookie.html')
    cookies = d.get_cookies()

    # brittle depends on how the cookies are ordered
    T.assert_equals(u'test2', cookies[1]['name'])
    T.assert_equals(u'test2', cookies[1]['value'])
    T.assert_equals(u'.localhost', cookies[1]['domain'])
    T.assert_equals(u'/', cookies[1]['path'])
    T.assert_equals(False, cookies[1]['secure'])
    T.assert_is_false(cookies[1].has_key('expiry'))
    T.assert_equals(2, len(cookies))
    T.assert_equals(u'test', cookies[0]['name'])
    T.assert_equals(u'test', cookies[0]['value'])
    T.assert_equals(u'.localhost', cookies[0]['domain'])
    T.assert_equals(u'/', cookies[0]['path'])
    T.assert_equals(False, cookies[0]['secure'])
    T.assert_is_true(cookies[0].has_key('expiry'))

@T.test
def getting_all_cookies_on_a_non_cookie_setting_page(d):
    go_to_page(d, '/hello.html')
    T.assert_equals(0, len(d.get_cookies()))

@T.test
def deleting_all_cookies(d):
    go_to_page(d, '/cookie.html')
    d.delete_all_cookies()
    cookies = d.get_cookies()
    T.assert_equals(0, len(cookies))

@T.test
def deleting_one_cookie(d):
    go_to_page(d, '/cookie.html')
    result = d.delete_cookie('test')
    cookies = d.get_cookies()
    T.assert_equals(1, len(cookies))
    T.assert_equals(u'test2', cookies[0]['name'])

@T.test
def adding_a_cookie(d):
    go_to_page(d, '')
    d.add_cookie({'name': u'newCookie', 'value': u'newValue'})
    cookies = d.get_cookies()
    T.assert_equals(1, len(cookies))
    T.assert_equals(u'newCookie', cookies[0]['name'])
    T.assert_equals(u'newValue', cookies[0]['value'])
    T.assert_equals(u'localhost', cookies[0]['domain'])
    T.assert_equals(u'/', cookies[0]['path'])
    T.assert_equals(False, cookies[0]['secure'])

@T.test
def modifying_a_cookie(d):
    go_to_page(d, '/cookie.html')

    d.add_cookie({
        'name': u'test',
        'value': u'newValue',
        'domain': 'localhost',
        'path': u'/',
        'secure': False})

    cookies = d.get_cookies()
    # brittle depends on how the cookies are ordered
    T.assert_equals(2, len(cookies))
    T.assert_equals(u'test2', cookies[1]['name'])
    T.assert_equals(u'test2', cookies[1]['value'])
    T.assert_equals(u'.localhost', cookies[1]['domain'])
    T.assert_equals(u'/', cookies[1]['path'])
    T.assert_equals(False, cookies[1]['secure'])
    T.assert_is_false(cookies[1].has_key('expiry'))
    T.assert_equals(u'test', cookies[0]['name'])
    T.assert_equals(u'newValue', cookies[0]['value'])
    T.assert_equals(u'.localhost', cookies[0]['domain'])
    T.assert_equals(u'/', cookies[0]['path'])
    T.assert_equals(False, cookies[0]['secure'])
    T.assert_is_false(cookies[0].has_key('expiry'))

@T.test
def should_retain_cookie_info(d):
    go_to_page(d, '')
    future_time = int(time.time()) + 100
    d.add_cookie({
        'name': u'fish',
        'value': u'cod',
        'path': u'/hello.html',
        'domain': u'localhost',
        'expiry': future_time,
    })
    T.assert_equals(d.get_cookie('fish'), None)

    go_to_page(d, 'hello.html')
    cookie = d.get_cookie('fish')
    T.assert_equals(u'fish', cookie['name'])
    T.assert_equals(u'cod', cookie['value'])
    T.assert_equals(False, cookie['secure'])
    T.assert_equals(future_time, cookie['expiry'])
    T.assert_equals(u'.localhost', cookie['domain'])

@T.test
def should_not_allow_to_create_cookie_on_different_domain(d):
    def _inner():
        go_to_page(d, '')
        cookie = {
            'name': u'fish',
            'value': u'cod',
            'path': u'/404',
            'domain': u'github.com'
        }
        d.add_cookie(cookie)
    T.assert_throws(WebDriverException, _inner)

@T.test
def should_allow_to_delete_cookies_even_if_not_set(d):
    go_to_page(d, '/cookie.html')
    T.assert_is_true(len(d.get_cookies()) > 0)
    d.delete_all_cookies()
    T.assert_equals(len(d.get_cookies()), 0)

    # All cookies deleted, call deleteAllCookies again. Should be a no-op.
    d.delete_all_cookies()
    d.delete_cookie('non_existing_cookie')
    T.assert_equals(len(d.get_cookies()), 0)


@T.test
def should_allow_to_set_cookie_that_is_already_expired(d):
    go_to_page(d, '/hello.html')
    d.add_cookie({
        'name': u'expired',
        'value': u'yes',
        'expiry': 631152000, # Monday, 01-Jan-90 00:00:00 UTC
    })
    cookie = d.get_cookie('expired')
    T.assert_equals(cookie, None)

@T.test
def should_throw_exception_if_adding_cookie_before_loading_any_url(d):
    def _inner():
        d.add_cookie({'name': u'x', 'value': u'123456789101112'})
    T.assert_throws(WebDriverException, _inner)

@T.test
def should_be_able_to_create_cookie_via_javascript(d):
    go_to_page(d, '/hello.html')

    d.execute_script('''
    document.cookie = 'test=test; path=/; domain=.localhost;';
    ''')
    cookie = d.get_cookie('test')
    T.assert_equals(u'test', cookie['value'])

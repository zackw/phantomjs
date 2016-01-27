
from urllib2 import URLError
from selenium.common.exceptions import NoSuchWindowException

@T.test
def quit_should_terminate_driver(d):
    d.get("about:blank")
    d.quit()
    # No process is left to respond
    T.assert_throws(URLError, lambda: d.current_window_handle)

@T.test
def opening_and_closing_windows(d):

    # 1 window is created initially
    T.assert_equals(len(d.window_handles), 1)

    # Navigation should not change the number of windows
    d.get("about:blank")
    T.assert_equals(len(d.window_handles), 1)

    # Open a second window from JS
    d.execute_script("""
        window.open(arguments[0] + '/hello.html', 'hello')
    """, T.http_base)
    T.assert_equals(len(d.window_handles), 2)

    # Close the initial window, one should remain
    d.close()
    T.assert_equals(len(d.window_handles), 1)

    # Switching to the 'hello' window should still be possible
    d.switch_to_window("hello")
    T.assert_not_equals(d.current_window_handle, None)

    # Close the remaining window
    d.close()
    T.assert_equals(len(d.window_handles), 0)

    # The driver is still alive but there are no windows left
    T.assert_throws(NoSuchWindowException, lambda: d.current_window_handle)

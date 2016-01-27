@T.test
def timeout_methods(d):
    # FIXME: This just tests that the timeout methods exist, not that
    # they *work*.
    #
    # Unlike Java, the Python bindings do not take a units argument;
    # all timeouts are specified in seconds.
    d.implicitly_wait(10)
    d.set_page_load_timeout(20)
    d.set_script_timeout(5)

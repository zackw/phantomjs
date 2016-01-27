import urllib

@T.test
def sync_queryselector(d):
    d.get(T.http_base + "/form.html")
    el = d.execute_script("""
        return document.querySelector("[name='"+arguments[0]+"']");
    """, "q")
    T.assert_not_equals(el, None)
    T.assert_equals(el.tag_name.lower(), u"input")

@T.test
def async_settimeout(d):
    d.get(T.http_base + "/form.html")
    res = d.execute_async_script("""
      window.setTimeout(arguments[arguments.length-1], arguments[0], 'done');
    """, 50)
    T.assert_equals(res, u"done")

@T.test
def async_with_multiple_arguments(d):
    d.set_script_timeout(0)
    d.get(T.http_base + "/form.html")
    res = d.execute_async_script("""
        arguments[arguments.length-1](arguments[0] + arguments[1]);
    """, 1, 2)
    T.assert_equals(res, 3)

    # navigating after an async script execution should not crash the driver
    d.get(T.http_base + "/hello.html")

@T.test
def async_multiple_scripts_sequentially(d):
    d.set_script_timeout(0)
    d.get(T.http_base + "/form.html")
    res = d.execute_async_script("""
        arguments[arguments.length-1](123);
    """)
    T.assert_equals(res, 123)
    res = d.execute_async_script("""
        arguments[arguments.length-1]('abc');
    """)
    T.assert_equals(res, u"abc")

    # navigating after an async script execution should not crash the driver
    d.get(T.http_base + "/hello.html")

@T.test
def async_multiple_scripts_with_navigation(d):
    for i in range(5):
        hello = "hello " + str(i)
        data = "data:text/html;charset=utf-8," + urllib.quote(
            "<h1>"+hello+"</h1>")
        d.get(data)
        h = d.execute_async_script("""
            arguments[arguments.length-1](
               document.getElementsByTagName('h1')[0].firstChild.textContent
            )
        """)
        T.assert_equals(hello, h.encode("utf-8"))

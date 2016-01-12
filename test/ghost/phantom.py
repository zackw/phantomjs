
# The PhantomJS-specific driver functionality that this test exercises
# is not exposed by the WebDriver Python bindings.

def add_pexecute_to_connection(d):
    if "executePhantomJS" not in d.command_executor._commands:
        d.command_executor._commands["executePhantomJS"] = (
            "POST", "/session/$sessionId/phantom/execute"
        )

def execute_phantomjs(d, script, *args):
    response = d.execute("executePhantomJS", {
        "script": script,
        "args": args
    })
    T.assert_is_true(u"value" in response)
    return response[u"value"]

@T.test
def test_execute_phantomjs(d):
    add_pexecute_to_connection(d)

    # Do we get results back?
    result = execute_phantomjs(d, "return 1 + 1")
    T.assert_equals(result, 2)

    # Can we read arguments?
    result = execute_phantomjs(d, "return arguments[0] * 2", 1)
    T.assert_equals(result, 2)

    # Can we override browser-provided JavaScript functions in the
    # page context?

    result = execute_phantomjs(d, """
        var page = this;
        page.onInitialized = function () {
            page.evaluate(function () {
                Math.random = function() { return 42 / 100 }
            })
        }""")

    d.get(T.http_base + "random.html")
    T.assert_equals(d.title, u"random numbers")

    numbers = d.find_element_by_id("numbers")
    found_one = False
    for number in numbers.text.split():
        found_one = True
        T.assert_equals(number, u"42")

    T.assert_is_true(found_one)

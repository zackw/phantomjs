import random
from string import letters
from selenium.common.exceptions import NoSuchElementException

def random_alphabetic(n):
    return "".join(random.choice(letters) for _ in range(n))

@T.test
def use_driver(d):
    d.get(T.http_base + 'hello.html')
    T.assert_equals(d.title, u'Hello')

##XXX Uncertain whether this harness feature is a good idea.
#@T.test(auto_quit_driver=False)
#def use_driver_manual_quit(d):
#    d.get(TEST_HTTP_BASE + 'hello.html')
#    d.quit()

##XXX This was 100 iterations in the original but that took 30 seconds(!)
## so it's been cut down to ten.
@T.test
def execute_many_times_the_same_command(d):
    d.get(T.http_base + 'hello.html')
    T.assert_equals(d.title, u'Hello')
    for _ in range(10):
        try:
            d.find_element_by_link_text(random_alphabetic(4))

        except NoSuchElementException:
            pass

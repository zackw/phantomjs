#! /usr/bin/env python

# This file is part of the PhantomJS project from Ofi Labs.
#
# Copyright 2015, 2016 Zachary Weinberg <zackw@panix.com>
#
# Based on testharness.js <https://github.com/w3c/testharness.js>
# produced by the W3C and distributed under the W3C 3-Clause BSD
# License <http://www.w3.org/Consortium/Legal/2008/03-bsd-license>.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the <organization> nor the
#     names of its contributors may be used to endorse or promote products
#     derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import division

import os
import sys

if __name__ == '__main__':
    lib_path   = os.path.normpath(os.path.dirname(os.path.abspath(__file__)))
    pylib_path = os.path.join(lib_path, 'py')
    if pylib_path not in sys.path:
        sys.path.insert(1, pylib_path)
        if os.environ.get('PYTHONPATH'):
            os.environ['PYTHONPATH'] = \
                pylib_path + os.pathsep + os.environ['PYTHONPATH']
        else:
            os.environ['PYTHONPATH'] = pylib_path

import argparse
import math
import re
import signal
import subprocess
import threading
import time
import traceback

from selenium.webdriver import PhantomJS

#
# Subprocess-related utilities
#

if hasattr(subprocess, 'DEVNULL'):
    def stdin_devnull(): return subprocess.DEVNULL

else:
    _devnull = None
    def stdin_devnull():
        global _devnull
        if _devnull is None:
            _devnull = open(os.devnull, "rb")
        return _devnull

if os.name == 'posix':
    import errno

    def _do_popen(args, kwargs):
        if 'preexec_fn' in kwargs:
            caller_preexec = kwargs['preexec_fn']
        else:
            caller_preexec = lambda: None

        def child_call_setpgid_and_chain():
            os.setpgid(0, 0)
            caller_preexec()

        kwargs['preexec_fn'] = child_call_setpgid_and_chain

        proc = subprocess.Popen(*args, **kwargs)

        # The parent process must _also_ call setpgid() to prevent a race.
        # See https://www.gnu.org/software/libc/manual/html_node/Launching-Jobs.html
        # We may get EACCES here if the child has already called execve();
        # in that case it has also already called setpgid() so no worries.
        pgid = proc.pid
        try:
            os.setpgid(pgid, pgid)
        except OSError as e:
            if e.errno != errno.EACCES:
                raise

        return (proc, pgid)

    def _do_send_signal(job, signal):
        os.killpg(job, signal)

    def _do_terminate(job):
        _do_send_signal(job, signal.SIGTERM)

    def _do_kill(job):
        _do_send_signal(job, signal.SIGKILL)

elif os.name == 'nt':
    import ctypes
    from ctypes.wintypes import HANDLE, LPVOID, UINT, BOOL, DWORD, LONG, ULONG

    # Nested job objects were added in Windows 8, which identifies
    # itself as 6.2 in getwindowsversion().
    ver = sys.getwindowsversion()
    if ver.major > 6 or (ver.major == 6 and ver.minor >= 2):
        _ADD_CREATIONFLAGS = 0x00000004 # CREATE_SUSPENDED
    else:
        _ADD_CREATIONFLAGS = 0x01000004 # CREATE_SUSPENDED|CREATE_BREAKAWAY

    def _ec_falsy_winerror(result, *etc):
        if not result:
            raise ctypes.WinError()
        return result

    def _ec_m1_winerror(result, *etc):
        if result < 0:
            raise ctypes.WinError()
        return result

    _kernel32 = ctypes.WinDLL("kernel32.dll")

    _kernel32.CreateJobObjectW.argtypes = (LPVOID, LPVOID)
    _kernel32.CreateJobObjectW.restype  = HANDLE
    _kernel32.CreateJobObjectW.errcheck = _ec_falsy_winerror

    _kernel32.TerminateJobObject.argtypes = (HANDLE, UINT)
    _kernel32.TerminateJobObject.restype  = BOOL
    _kernel32.TerminateJobObject.errcheck = _ec_falsy_winerror

    _kernel32.AssignProcessToJobObject.argtypes = (HANDLE, HANDLE)
    _kernel32.AssignProcessToJobObject.restype  = BOOL
    _kernel32.AssignProcessToJobObject.errcheck = _ec_falsy_winerror

    _kernel32.CloseHandle.argtypes  = (HANDLE,)
    _kernel32.CloseHandle.restype   = BOOL
    _kernel32.CloseHandle.errcheck  = _ec_falsy_winerror

    # defensiveness against handle leakage
    class wrap_HANDLE(object):
        __slots__ = ('_h',)
        def __init__(self, h): self._h = h
        def __int__(self): return self._h
        def __nonzero__(self): return bool(self._h)

        def __del__(self, _CloseHandle=_kernel32.CloseHandle):
            if self._h:
                _CloseHandle(self._h)
                self._h = 0

        close = __del__

    # subprocess.Popen retains the process handle but not the thread
    # handle, which we need to resume the suspended thread.  The only
    # *documented* way to recover a thread handle appears to be using
    # the "tool help" API, which, fortunately, is in kernel32 since
    # XP.  NtResumeProcess is better if available; it's undocumented
    # but reportedly has also been around since XP; prepare for the
    # possibility of its not existing.
    try:
        _ntdll = ctypes.WinDLL("ntdll.dll")

        # This is *probably* the right way to convert a NTSTATUS code
        # to a GetLastError code; it appears to have been documented
        # only grudgingly.
        _ntdll.RtlNtStatusToDosError.argtypes = (LONG,)
        _ntdll.RtlNtStatusToDosError.restype  = ULONG
        #_ntdll.RtlNtStatusToDosError cannot fail

        def _ec_ntstatus(status, *etc):
            if status < 0:
                raise ctypes.WinError(_ntdll.RtlNtStatusToDosError(status))
            return status

        _ntdll.NtResumeProcess.argtypes = (HANDLE,)
        _ntdll.NtResumeProcess.restype  = LONG
        _ntdll.NtResumeProcess.errcheck = _ec_ntstatus

        def _resume_threads(hproc, pid):
            _ntdll.NtResumeProcess(hproc)

        _RESUME_THREADS_IMPL = "NtResumeProcess"

    except AttributeError:

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", DWORD),
                ("cntUsage", DWORD),
                ("th32ThreadID", DWORD),
                ("th32OwnerProcessID", DWORD),
                ("tpBasePri", LONG),
                ("tpDeltaPri", LONG),
                ("dwFlags", DWORD),
            ]
        LPTHREADENTRY32 = ctypes.POINTER(THREADENTRY32)

        _kernel32.CreateToolhelp32Snapshot.argtypes = (DWORD, DWORD)
        _kernel32.CreateToolhelp32Snapshot.restype = HANDLE
        _kernel32.CreateToolhelp32Snapshot.errcheck = _ec_falsy_winerror

        _kernel32.Thread32First.argtypes = (HANDLE, LPTHREADENTRY32)
        _kernel32.Thread32First.restype = BOOL
        _kernel32.Thread32First.errcheck = _ec_falsy_winerror

        _kernel32.Thread32Next.argtypes = (HANDLE, LPTHREADENTRY32)
        _kernel32.Thread32Next.restype = BOOL
        #_kernel32.Thread32Next cannot fail

        _kernel32.OpenThread.argtypes = (DWORD, BOOL, DWORD)
        _kernel32.OpenThread.restype  = HANDLE
        _kernel32.OpenThread.errcheck = _ec_falsy_winerror

        _kernel32.ResumeThread.argtypes = (HANDLE,)
        _kernel32.ResumeThread.restype  = DWORD
        _kernel32.ResumeThread.errcheck = _ec_m1_winerror

        def _resume_threads(hproc, pid):
            thblock = THREADENTRY32()
            thblock.dwSize = ctypes.sizeof(thblock)
            byref = ctypes.byref
            try:
                # TH32CS_SNAPTHREAD (0x4) gives us all threads on the whole
                # system, and we have to filter them.  There's no way to get
                # kernel32 to do that for us.
                hsnap = _kernel32.CreateToolhelp32Snapshot(0x4, 0)
                _kernel32.Thread32First(hsnap, byref(thblock))
                while True:
                    if thblock.th32OwnerProcessID == pid:
                        try:
                            hthread = _kernel32.OpenThread(
                                0x0002, # THREAD_SUSPEND_RESUME
                                False, thblock.th32ThreadID)
                            _kernel32.ResumeThread(hthread)
                        finally:
                            _kernel32.CloseHandle(hthread)

                    if not _kernel32.Thread32Next(hsnap, byref(thblock)):
                        break

            finally:
                _kernel32.CloseHandle(hsnap)

        _RESUME_THREADS_IMPL = "Toolhelp32"

    def _do_popen(args, kwargs):
        job = _kernel32.CreateJobObjectW(None, None)

        flags = kwargs.get('creationflags', 0)
        flags |= _ADD_CREATIONFLAGS
        kwargs['creationflags'] = flags

        proc = subprocess.Popen(*args, **kwargs)

        _kernel32.AssignProcessToJobObject(job, int(proc._handle))
        _resume_threads(int(proc._handle), proc.pid)

        return (proc, wrap_HANDLE(job))

    def _do_send_signal(job, sig):
        if sig == signal.SIGTERM:
            _do_terminate(job)
        else:
            # There's no way to send CTRL_C_EVENT or CTRL_BREAK_EVENT to an
            # entire job, as far as I can tell.
            raise ValueError("Unsupported signal: {}".format(sig))

    def _do_terminate(job):
        try:
            hjob = int(job)
            if hjob:
                _kernel32.TerminateJobObject(hjob, 1)
                job.close()
        except OSError as e:
            # Comments in Windows subprocess.terminate() say that
            # "ERROR_ACCESS_DENIED (winerror 5) is received when the
            # process already died."  MSDN does not document whether
            # this is true for job objects, but it seems plausible.
            if e.winerror != 5:
                raise
            # We are not in a position to call GetExitCodeProcess here.
            # Just leave it to subprocess.poll().

    def _do_kill(job):
        _do_terminate(job)

else:
    raise ValueError('sorry, not implemented: process groups for ostype "{}"'
                     .format(os.name))

class Job(object):
    """A Job object wraps a subprocess.Popen object; it is functionally
       identical, except that terminate() and kill() are applied to
       all child processes _of_ the child process, as well as the
       child process itself.  Moreover, when the child process exits,
       all of its children are killed.

       On Unix, this is accomplished with process groups; on Windows,
       with job objects.  Descendant processes _can_ escape containment;
       on Unix, by using setpgid(); on Windows, by being created as
       "breakaway" processes.

       On Unix, send_signal() is also applied to the process group; on
       Windows, this only works for signal.SIGTERM (which is mapped to
       terminate()).
    """

    def __init__(self, *args, **kwargs):
        if len(args) > 1:
            raise TypeError("Job() optional arguments must be specified as "
                            "keyword arguments")

        self._proc, self._job = _do_popen(args, kwargs)

    def send_signal(self, signal):
        _do_send_signal(self._job, signal)

    def terminate(self):
        _do_terminate(self._job)

    def kill(self):
        _do_kill(self._job)

    def poll(self):
        rv = self._proc.poll()
        if rv is not None and self._job is not None:
            _do_terminate(self._job)
            self._job = None
        return rv

    # Forward all other actions to _proc.
    def __getattr__(self, aname):
        return getattr(self._proc, aname)

#
# Other utilities
#

regex_type = type(re.compile("blah"))

regex_flags = [
    (re.I, 'i'),
    (re.L, 'l'),
    (re.M, 'm'),
    (re.S, 's'),
    (re.U, 'u'),
    (re.X, 'x')
]
def format_re(rx):
    if isinstance(rx, regex_type):
        pat  = rx.pattern
        flgs = rx.flags
    else:
        pat  = rx
        flgs = 0

    pat = '/' + pat.replace('/', '\\/') + '/'
    if flgs:
        dflg = []
        for flag, letter in regex_flags:
            if flgs & flag:
                dflg.append(letter)
        pat += "".join(dflg)
    return pat

def format_assert(caller, desc, msg, substs):
    if desc:
        desc += ": "
    else:
        desc = ""
    return ("{caller}: {desc} " + msg).format(caller=caller,
                                              desc=desc,
                                              **substs)

def format_exception(ty, vl, tb, prefix=''):
    msg = []
    if ty is TestAssertionError:
        msg.extend(str(vl).splitlines())
    else:
        for block in traceback.format_exception_only(ty, vl):
            msg.extend(block.splitlines())
        if ty.__name__ not in msg[0]:
            msg[0] = ty.__name__ + ": " + msg[0]

    trace = traceback.extract_tb(tb)
    trace.reverse() # down with backward exception traces

    # Chop off the leading traceback entries for assertion-generating
    # functions (if any), and the trailing traceback entries for
    # code leading to the test function.
    for i in range(len(trace)):
        if trace[i][0] != __file__ or 'assert' not in trace[i][2]:
            break
    for j in range(i, len(trace)):
        if trace[i][0] == __file__:
            break

    for block in traceback.format_list(trace[i:j]):
        msg.extend(block.splitlines())

    return ''.join(prefix + line + '\n'
                   for line in msg)


class TestAssertionError(RuntimeError):
    def __init__(self, caller, desc, msg, substs):
        self.caller = caller
        self.desc = desc
        self.msg = msg
        self.substs = substs

    def __str__(self):
        return format_assert(self.caller, self.desc, self.msg, self.substs)

def same_value(x, y):
    """True if 'x' and 'y' are strictly, strictly (but shallowly) equal.
       This function is not part of the test-script API, but its
       _behavior_ is part of the contract of several assert_* functions.

       Unlike the JavaScript version, we can rely on '==' to do the
       Right Thing in nearly all cases; the only tweaks required are
       IEEE754-related.
    """
    if x == y:
        # Distinguish +0 and -0
        if x == 0:
            return math.copysign(1, x) == math.copysign(1, y)
        return True
    elif isinstance(x, float):
        # Treat NaN as equal to itself.
        if math.isnan(x):
            return math.isnan(y)
    return False

#
# Enumerations
#

class TestStatus:
    PASS         = 0
    FAIL         = 1
    XFAIL        = 2
    XPASS        = 3
    NOTRUN       = 4

#
# Test harness classes
#

class BaseTestRunner(object):
    """The TestRunner classes are responsible for high-level sequencing
       of a set of test cases."""

    def __init__(self, pjs_command, verbose):
        self.pjs_command     = pjs_command
        self.verbose         = verbose
        self.ntests          = 0
        self.default_timeout = 1000 # milliseconds
        self.driver_args     = None

    def handle_load_failure(self, script, exc_info):
        raise NotImplemented

    def output_info(self, message):
        raise NotImplemented

    def add_test(self, name, testfn, **properties):
        raise NotImplemented

    def setup(self, **properties):
        raise NotImplemented

    def run_tests(self):
        raise NotImplemented

    def result(self, test):
        raise NotImplemented

    def get_child_cmdline(self, test_name):
        raise NotImplemented

class ChildTestRunner(BaseTestRunner):
    """ChildTestRunner is used in per-test child processes, and will
       only run one test, as instructed by the test_name argument to the
       constructor."""

    def __init__(self, test_name, *args):
        BaseTestRunner.__init__(self, *args)
        self.test_name   = test_name
        self.test_obj    = None
        self.driver_args = {
            "executable_path": self.pjs_command[0],
            "service_args":    self.pjs_command[1:]
        }

    def handle_load_failure(self, script, exc_info):
        sys.stdout.write("ERROR: While reading test script:\n")
        sys.stdout.write(format_exception(*exc_info))
        sys.exit(1)

    def output_info(self, message):
        for line in message.splitlines():
            sys.stdout.write("# " + line + "\n")

    def add_test(self, name, testfn, **properties):
        self.ntests += 1
        if name != self.test_name: return
        if self.test_obj:
            sys.stdout.write("ERROR: (can't happen) duplicate test name {}\n"
                             .format(name))
            sys.exit(1)

        self.test_obj = Test(self, name, testfn, self.ntests, **properties)

    def setup(self, driver_args=None, **other):
        """The only setup property we need to handle here is driver_args.
           Validation happens in the parent."""
        if driver_args:
            if isinstance(driver_args, dict):
                if 'port' in driver_args:
                    self.driver_args['port'] = driver_args['port']
                if 'desired_capabilities' in driver_args:
                    self.driver_args['desired_capabilities'] = \
                        driver_args['desired_capabilities']
                if 'service_args' in driver_args:
                    self.driver_args['service_args'].extend(
                        driver_args['service_args'])

            else:
                self.driver_args['service_args'].extend(driver_args)

    def run_tests(self):
        if self.test_obj is None:
            sys.stdout.write("ERROR: (can't happen) no test named {}\n"
                             .format(self.test_name))
            sys.exit(1)
        self.test_obj.run_child()

        # run_child() isn't supposed to return
        sys.stdout.write("ERROR: (can't happen) run_child returned\n")
        sys.exit(1)

    # get_child_cmdline() will never be called

class ParentTestRunner(BaseTestRunner):
    """ParentTestRunner is used in the parent process, and is responsible
       for sequencing execution of each test, collecting the results,
       and writing out TAP-format output to be consumed by run-tests.py.
    """
    def __init__(self, test_script, *args):
        BaseTestRunner.__init__(self, *args)
        self.test_script = test_script
        self.tests       = []
        self.tnames      = set()
        self.failed      = False
        self.skip        = False

    def handle_load_failure(self, script, exc_info):
        sys.stdout.write("# ERROR: While reading test script:\n")
        sys.stdout.write(format_exception(*exc_info, prefix='# '))
        sys.stdout.flush()
        self.skip   = "error while reading test script"
        self.failed = True

    def output_info(self, message):
        for line in message.splitlines():
            if not line:
                sys.stdout.write("##\n")
            elif line[0] == '#':
                sys.stdout.write("##" + line + "\n")
            else:
                sys.stdout.write("## " + line + "\n")
            sys.stdout.flush()

    def add_test(self, name, testfn, **properties):
        if name in self.tnames:
            sys.stdout.write("# ERROR: duplicate test name '{}'\n"
                             .format(name))
            sys.stdout.flush()
            self.skip   = "duplicated test names"
            self.failed = True
            return

        self.tnames.add(name)
        self.ntests += 1
        self.tests.append(
            Test(self, name, testfn, self.ntests, **properties))

    def setup(self,
              default_timeout=None,
              skip_if=None,
              driver_args=None):
        """Global configuration properties are:

           default_timeout (positive real): Default per-test timeout, in
               milliseconds.
               Unlike testharness.js, this harness has no *overall* timeout,
               but it imposes a default timeout of one second on each test.

           skip_if: If not None, this should be a callable which will
               be invoked (with no arguments) to decide whether the
               entire test group should be skipped.  It should either
               return a falsey value, in which case the tests *will*
               be run; or a truthy string, in which case the tests
               will *not* be run, and the string will be recorded as
               the reason why the tests are not being run.

           driver_args: Additional arguments to pass to the GhostDriver
               constructor (applies to all tests in the file).  This can
               be either a dict, or an iterable; specifying an iterable
               is shorthand for specifying { 'service_args': iterable }.
        """
        if default_timeout is not None:
            if default_timeout > 0:
                self.default_timeout = default_timeout
            else:
                sys.stdout.write(
                    "# ERROR: default timeout must be positive, not {!r}\n"
                    .format(default_timeout))
                sys.stdout.flush()
                self.skip = "error in global setup"
                self.failed = True


        # driver_args is handled in the child, but must be validated
        # here.  Note: hardcoded list of acceptable constructor arguments
        # (keep in sync with py/selenium/webdriver/phantomjs/webdriver.py).
        if driver_args is not None:
            if isinstance(driver_args, dict):
                not_allowed_keys = set(driver_args.keys()) - frozenset(
                    "port", "desired_capabilities", "service_args")
                if not_allowed_keys:
                    sys.stdout.write(
                        "# ERROR: not allowed in driver_args: "
                        + " ".join(not_allowed_keys) + "\n")
                    sys.stdout.flush()
                    self.skip = "error in global setup"
                    self.failed = True
            else:
                try:
                    driver_args = list(driver_args)
                except Exception:
                    sys.stdout.write("# ERROR: " +
                                     format_exception(*sys.exc_info(),
                                                      prefix="# "))
                    sys.stdout.flush()
                    self.skip = "error in global setup"
                    self.failed = True


        if skip_if is not None:
            if not callable(skip_if):
                sys.stdout.write(
                    "# ERROR: skip_if must be a callable, not {!r}"
                    .format(skip_if))
                sys.stdout.flush()
                self.skip = "error in global setup"
                self.failed = True

            why = skip_if()
            if why:
                if not isinstance(why, str):
                    sys.stdout.write(
                        "# ERROR: skip_if returned a truthy non-string, {!r}"
                        .format(why))
                    sys.stdout.flush()
                    self.skip = "error in global setup"
                    self.failed = True

                if self.skip:
                    # we're already skipping, just log it
                    sys.stdout.write(
                        "## skip_if={!r}".format(why))
                    sys.stdout.flush()
                else:
                    self.skip = why
                    # this is *not* considered a failure

    def run_tests(self):
        if self.skip:
            sys.stdout.write("1..0 # SKIP: " + self.skip + "\n")
            sys.stdout.flush()

            if self.failed:
                sys.exit(1)
            else:
                sys.exit(0)

        if self.failed:
            sys.stdout.write("# ERROR: failed during setup with no message\n")
            sys.stdout.write("1..0 # SKIP\n")
            sys.stdout.flush()
            sys.exit(1)

        sys.stdout.write("1..{}\n".format(self.ntests))
        sys.stdout.flush()

        for t in self.tests:
            t.run_parent()

            if t.message:
                for line in t.message.splitlines():
                    if not line:
                        sys.stdout.write("#\n")
                    elif line[0] == '#':
                        sys.stdout.write("#" + line + "\n")
                    else:
                        sys.stdout.write("# " + line + "\n")
                sys.stdout.flush()

            prefix = None
            directive = ""
            if t.status == TestStatus.PASS:
                prefix = "ok "
            elif t.status == TestStatus.FAIL:
                prefix = "not ok "
                self.failed = True
            elif t.status == TestStatus.XPASS:
                prefix = "ok "
                directive = " # TODO"
                self.failed = True
            elif t.status == TestStatus.XFAIL:
                prefix = "not ok "
                directive = " # TODO"
            elif status == TestStatus.NOTRUN:
                prefix = "ok "
                directive = " # SKIP"
            else:
                self.error("Unrecognized test status {}".format(t.status))
                prefix = "not ok "

            sys.stdout.write("{}{} {}{}\n".format(prefix, t.number, t.name,
                                                  directive))
            sys.stdout.flush()

        if self.failed:
            sys.exit(1)
        else:
            sys.exit(0)

    def get_child_cmdline(self, test_name):
        return [
            sys.executable,
            __file__,
            "--verbose={}".format(self.verbose),
            "--test-name=" + test_name,
            self.test_script
        ] + self.pjs_command


class Test(object):
    """Test object.  These must be created by using the @T.test decorator.

       A Test object wraps a _test function_, which is the decorated
       function; it will be called with a single argument, which is a
       GhostDriver instance.  If this function returns normally, the
       test is successful (any return value is ignored).  If it throws
       a TestAssertionError, the test has failed.  If it throws any
       other sort of exception, the test is in an "error" state.

       To use the keyword arguments to the Test constructor, supply
       keyword arguments to the @T.test decorator, e.g.

       @T.test(expected_fail=True)
       def this_doesnt_work_but_should(d):
           ...

       The keyword arguments are:

           - timeout (positive real): Amount of time the test is allowed
             to run, in milliseconds.

           - expected_fail: If true, the test is expected to fail.

           - skip: If true, the test will not be run at all.  Use this
             only if there's some reason why the test doesn't make
             sense, or can't safely even be *attempted*.

           - driver_args: Dictionary of additional keyword arguments
             to pass to the GhostDriver constructor.  This may also be
             an iterable, which is shorthand for { 'service_args': iterable }.
             Note that not all GhostDriver constructor args are allowed.
    """

    def __init__(self, runner, name, testfn, number,
                 timeout=None, skip=False, expected_fail=False,
                 auto_quit_driver=True, driver_args=None):

        self.runner      = runner
        self.name        = name
        self.testfn      = testfn
        self.number      = number
        self.status      = TestStatus.NOTRUN
        self.message     = None
        self.xfail       = expected_fail
        self.skip        = skip

        if not driver_args:
            self.driver_args = {}

        elif isinstance(driver_args, dict):
            not_allowed_keys = set(driver_args.keys()) - frozenset(
                "port", "desired_capabilities", "service_args")
            if not_allowed_keys:
                raise ValueError(
                    "not allowed in driver_args: "
                    + " ".join(not_allowed_keys) + "\n")
            self.driver_args = driver_args

        else:
            self.driver_args = { 'service_args': list(driver_args) }

        if timeout is None:
            self.timeout = runner.default_timeout
        elif timeout > 0:
            self.timeout = timeout
        else:
            raise ValueError("{}: timeout must be a positive number, not {!r}"
                             .format(name, timeout))


    def run_parent(self):
        """Called only in the parent: spawn a child process to execute this
           test, and record the results.  (We use a child process for each
           test primarily because this gives us a way to implement timeouts,
           but it also serves to isolate each test from the others - each
           test gets its own fresh GhostDriver instance.)
        """
        if self.skip:
            return

        job = Job(self.runner.get_child_cmdline(self.name),
                  stdin=stdin_devnull(),
                  stdout=subprocess.PIPE)

        # We don't use communicate(timeout=) because it's not available
        # until Python 3.3, and loses output emitted before the timeout
        # until Python 3.5.
        timed_out = False
        def on_timeout():
            job.terminate()
            timed_out = True

        timer = threading.Timer(self.timeout / 1000., on_timeout)
        (stdout, _) = job.communicate()
        if stdout and stdout[-1] != '\n': stdout += '\n'
        if timed_out:
            # This is an automatic failure, and we ignore the return code
            # (which will vary between Unix and Windows).  Consistent with
            # testharness.js, this is *not* considered an error.
            self.status = TestStatus.FAIL
            stdout += 'Test timed out\n'

        else:
            timer.cancel()
            if job.returncode == 0:
                self.status = TestStatus.PASS
            elif job.returncode == 1:
                self.status = TestStatus.FAIL
            else:
                self.status = TestStatus.FAIL

                stdout += 'ERROR: unexpected exit status {}\n'.format(
                    job.returncode)

        self.message = stdout

        if self.xfail:
            if self.status == TestStatus.FAIL:
                self.status = TestStatus.XFAIL
            elif self.status == TestStatus.PASS:
                self.status = TestStatus.XPASS

    def run_child(self):
        """Called only in the child: actually execute the test."""

        try:
            driver_args = self.runner.driver_args.copy()
            for k, v in self.driver_args.items():
                if k == 'service_args':
                    driver_args['service_args'].extend(v)
                else:
                    driver_args[k] = v

            driver = None
            try:
                driver = PhantomJS(**driver_args)
                self.testfn(driver)
            finally:
                if driver is not None:
                    # XXX Is it safe to do this unconditionally?
                    # If the driver has already crashed, will we
                    # get "fallout" exceptions?
                    driver.quit()

            sys.exit(0)

        except TestAssertionError:
            sys.stdout.write(format_exception(*sys.exc_info()))
            sys.exit(1)

        except Exception:
            sys.stdout.write('ERROR: ' + format_exception(*sys.exc_info()))
            sys.exit(1)

class TestContext(object):
    """An instance of this class is exposed as the global 'T' in the
       test script.  This class is also responsible for parsing the
       test script itself, and reporting the set of test functions to
       the test runner.  (Note that there are two test runner classes,
       one used in the parent process and one in each per-test subprocess.)

       All properties and methods of this object whose names start with
       zero underscores are public for use by test scripts.  Data properties
       should be treated as read-only (this is not currently enforced).

       All properties and methods of this object whose names start with
       one or more underscores are internal-use-only.
    """

    def __init__(self, runner, verbose, test_script):
        # Data exposed to test scripts
        self.http_base  = os.environ['TEST_HTTP_BASE']
        self.https_base = os.environ['TEST_HTTPS_BASE']
        self.test_dir   = os.environ['TEST_DIR']
        self.script     = test_script

        # Internal use only
        self._runner    = runner
        self._verbose   = verbose
        self._testmod   = { "T": self }

        # Load the test script
        try:
            execfile(self.script, self._testmod)
        except Exception:
            self._runner.handle_load_failure(self.script, sys.exc_info())

    def _assert(self, expr, caller, desc, msg, substs):
        if not expr:
            raise TestAssertionError(caller, desc, msg, substs)
        elif self._verbose >= 4:
            self._runner.output_info(format_assert(caller, desc, msg, substs))

    def test(self, _fn=None, **properties):
        """Decorator: FN is a test function.  This decorator can be used
           either with or without explicit keyword arguments.  See the
           Test constructor for the set of meaningful keyword arguments.
        """
        def do_decorate_test(fn):
            assert callable(fn)
            self._runner.add_test(fn.__name__, fn, **properties)
            return fn

        if _fn is None:
            return do_decorate_test
        else:
            return do_decorate_test(_fn)


    def setup(self, **properties):
        """Configure this entire group of tests.  See TestRunner.setup
           for the list of properties and their meanings.
        """
        self._runner.setup(**properties)

    # Note: the assertions all have the same _names_ as the testharness.js
    # assertions, but they have slightly different _semantics_, in keeping
    # with Python's slightly different object model.
    #
    # assert_deep_equals, assert_in_array, assert_approx_equals,
    # assert_own_property, assert_inherits, assert_no_property will be
    # added if and when they turn out to be useful; we suspect they
    # aren't needed for this.  assert_class_string and assert_readonly
    # doesn't make sense in Python, and assert_throws is very
    # different.

    def assert_is_true(self, actual, description=None):
        """Assert that |actual| is strictly true."""
        self._assert(actual == True, "assert_is_true", description,
                     "expected True got {actual!r}", {'actual': actual})

    def assert_is_false(self, actual, description=None):
        """Assert that |actual| is strictly false."""
        self._assert(actual == False, "assert_is_false", description,
                     "expected False got {actual!r}",
                     {'actual': actual})

    def assert_equals(self, actual, expected, description=None):
        """Assert that |actual| is strictly equal to |expected|.
           The test is even more stringent than == (see same_value)."""
        self._assert(type(actual) == type(expected),
                     "assert_equals", description,
                     "expected {expectedT} got {actualT}",
                     {'expectedT': type(expected),
                      'actualT':   type(actual)})
        self._assert(same_value(actual, expected),
                     "assert_equals", description,
                     "expected {expected!r} got {actual!r}",
                     {'expected': expected, 'actual': actual})

    def assert_not_equals(self, actual, expected, description=None):
        """Assert that |actual| is not strictly equal to |expected|, using the
           same extra-stringent criterion as for assert_equals."""
        self._assert(not same_value(actual, expected),
                     "assert_not_equals", description,
                     "got disallowed value {actual!r}",
                     {'actual': actual})

    def assert_less_than(self, actual, expected, description=None):
        """Assert that |actual| is less than |expected|."""
        self._assert(actual < expected,
                     "assert_less_than", description,
                     "expected a number less than {expected!r} "
                     "but got {actual!r}",
                     {'expected': expected, 'actual': actual})

    def assert_less_than_equal(self, actual, expected, description=None):
        """Assert that |actual| is less than or equal to |expected|."""
        self._assert(actual <= expected,
                     "assert_less_than_equal", description,
                     "expected a number less than or equal to {expected!r} "
                     "but got {actual!r}",
                     {'expected': expected, 'actual': actual})

    def assert_greater_than(self, actual, expected, description=None):
        """Assert that |actual| is greater than |expected|."""
        self._assert(actual > expected,
                     "assert_greater_than", description,
                     "expected a number greater than {expected!r} "
                     "but got {actual!r}",
                     {'expected': expected, 'actual': actual})

    def assert_greater_than_equal(self, actual, expected, description=None):
        """Assert that |actual| is greater than or equal to |expected|."""
        self._assert(actual >= expected,
                     "assert_greater_than_equal", description,
                     "expected a number greater than or equal to {expected!r} "
                     "but got {actual!r}",
                     {'expected': expected, 'actual': actual})

    def assert_regexp_match(self, actual, expected, description=None):
        """Assert that |actual|, a string, matches a regexp, |expected|.
           |expected| may be either a compiled regex object or a string;
           in the latter case it will be compiled with the default regex
           options.  "Matches" means re.search(), *not* re.match()."""

        if isinstance(expected, regex_type):
            m = expected.search(actual)
        else:
            m = re.search(expected, actual)

        self._assert(m is not None, "assert_regexp_match", description,
                     "expected {actual!r} to match {expected}",
                     {'expected': format_re(expected), 'actual': actual})

    def assert_regexp_not_match(self, actual, expected, description=None):
        """Assert that |actual|, a string, does not match a regexp,
        |expected|.  |expected| may be either a compiled regex object or a
        string; in the latter case it will be compiled with the default regex
        options.  "Matches" means re.search(), *not* re.match()."""

        if isinstance(expected, regex_type):
            m = expected.search(actual)
        else:
            m = re.search(expected, actual)

        self._assert(m is None, "assert_regexp_match", description,
                     "expected {actual!r} not to match {expected}",
                     {'expected': format_re(expected), 'actual': actual})

    def assert_type_of(self, obj, xtype, description=None):
        """Assert that type(|obj|) == |xtype|.  Does not work with
           old-style classes."""

        self._assert(isinstance(xtype, type), "assert_type_of", description,
                     "expected {xtype!r} to be a type, not a {xatype}",
                     {'xtype': xtype, 'xatype': type(xatype).__name__})

        self._assert(type(obj) == xtype, "assert_type_of", description,
                     "expected type of {obj!r} to be {xtype}, got {atype}",
                     {'obj': obj, 'xtype': xtype.__name__,
                      'atype': type(obj).__name__})

    def assert_instance_of(self, obj, cls, description=None):
        """Asssert that |obj| is an instance of |cls|.
           |cls| may be anything acceptable as the second argument to
           isinstance()."""

        self._assert(isinstance(obj, cls), "assert_instance_of", description,
                     "expected {obj!r} to be an instance of {cls!r}",
                     {'obj': obj, 'cls': cls})

    def assert_throws(self, excs, func, description=None):
        """Assert that |func| throws one of the exception types |excs|.

           Specifically, it is an error if |func| doesn't throw an
           exception, or if it throws something that is an instance of
           Exception but not an instance of one of the |excs|.  If it
           throws something that *isn't* an instance of Exception, that
           won't be caught at all.

           |func| is called with no arguments.
        """

        try:
            func()

        except Exception as e:
            self._assert(isinstance(e, excs), "assert_throws", description,
                         "expected {func} to throw {excs!r} but got {e}",
                         {'func': func, 'excs': excs, 'e': e})

        else:
            self._assert(False, "assert_throws", description,
                         "{func} did not throw an exception",
                         {'func': func})

    def assert_unreached(self, description=None):
        """Assert that control flow cannot reach the point where this
           assertion appears."""
        self._assert(False, "assert_unreached", description,
                     "reached unreachable code", {})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", type=int, default=0, const=1, nargs='?')
    ap.add_argument("--test-name", help="(internal use only)")
    ap.add_argument("test_script")
    ap.add_argument("pjs_command", nargs=argparse.REMAINDER)

    args = ap.parse_args()

    if args.test_name:
        runner = ChildTestRunner(args.test_name,
                                 args.pjs_command, args.verbose)
    else:
        runner = ParentTestRunner(args.test_script,
                                  args.pjs_command, args.verbose)

    context = TestContext(runner, args.verbose, args.test_script)
    runner.run_tests()

if __name__ == '__main__':
    main()

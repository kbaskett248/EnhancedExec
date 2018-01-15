from contextlib import contextmanager
import logging
import os
import sys
import subprocess
import threading
import time
import tempfile

import sublime

logger = logging.getLogger(__name__)
logger.setLevel('DEBUG')

try:
    from Default.exec import AsyncProcess, ExecCommand
except ImportError as e:
    logger.error('Default package is not installed')
    raise e


@contextmanager
def updated_environ(env):
    old_env = os.environ.copy()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ = old_env


class EnhancedAsyncProcess(AsyncProcess):
    """
    Extends AsyncProcess to retrieve results from file rather than stdout.
    """

    def __init__(self, cmd, shell_cmd, env, listener,
                 # startup_info is an option in build systems
                 startup_info=True,
                 # "path" is an option in build systems
                 path="",
                 # "shell" is an option in build systems
                 shell=False,
                 # "results_file_path" is an option in build systems
                 results_file_path=None,
                 wait=None):

        if not shell_cmd and not cmd:
            raise ValueError("shell_cmd or cmd is required")

        if shell_cmd and not isinstance(shell_cmd, str):
            raise ValueError("shell_cmd must be a string")

        self.listener = listener
        self.killed = False
        self._delete_results_file = False
        self.results_file_path = results_file_path

        self.start_time = time.time()

        # Hide the console window on Windows
        startupinfo = None
        if startup_info and os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        with updated_environ(env):
            proc_env = os.environ.copy()
            if path:
                proc_env['PATH'] = path
            for k, v in proc_env.items():
                proc_env[k] = os.path.expandvars(v)

        if shell_cmd:
            if '<result_file>' in shell_cmd:
                if not self.results_file_path:
                    self.create_results_file()
                shell_cmd = shell_cmd.replace('<result_file>',
                                              self.results_file_path)
                logger.debug("shell_cmd: %s", shell_cmd)

            if sys.platform == "win32":
                # Use shell=True on Windows, so shell_cmd is passed through
                # with the correct escaping
                self.proc = subprocess.Popen(
                    shell_cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    startupinfo=startupinfo, env=proc_env, shell=True)
            elif sys.platform == "darwin":
                # Use a login shell on OSX, otherwise the users expected env
                # vars won't be setup
                self.proc = subprocess.Popen(
                    ["/bin/bash", "-l", "-c", shell_cmd],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    startupinfo=startupinfo, env=proc_env, shell=False)
            elif sys.platform == "linux":
                # Explicitly use /bin/bash on Linux, to keep Linux and OSX as
                # similar as possible. A login shell is explicitly not used for
                # linux, as it's not required
                self.proc = subprocess.Popen(
                    ["/bin/bash", "-c", shell_cmd],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    startupinfo=startupinfo, env=proc_env, shell=False)
        else:
            if isinstance(cmd, str):
                if '<result_file>' in shell_cmd:
                    if not self.results_file_path:
                        self.create_results_file()
                    cmd = cmd.replace('<result_file>', self.results_file_path)
            else:
                updated_cmd = []
                for a in cmd:
                    if '<result_file>' in a:
                        if not self.results_file_path:
                            self.create_results_file()
                        a.replace('<result_file>', self.results_file_path)
                    updated_cmd.append(a)
                cmd = updated_cmd

            # Old style build system, just do what it asks
            self.proc = subprocess.Popen(cmd, env=proc_env, shell=shell)

        if self.proc.stdout:
            threading.Thread(target=self.read_stdout).start()

        if self.proc.stderr:
            threading.Thread(target=self.read_stderr).start()

        if self.results_file_path:
            threading.Thread(target=self.read_results_from_file).start()

        if wait:
            self.proc.wait(timeout=wait)

    def read_results_from_file(self):
        """
        Loop while the process runs and read the results file. When the
        process completes, delete the results file if it was created by this
        process.

        """
        with open(self.results_file_path, 'rb') as f:
            while True:
                data = f.read()

                if len(data) > 0:
                    if self.listener:
                        self.listener.on_data(self, data)
                else:
                    if self.killed or (not self.poll()):
                        break
                time.sleep(0.01)
            logger.debug("exiting file read loop")

        self.delete_results_file()

    def kill(self):
        super(EnhancedAsyncProcess, self).kill()
        self.delete_results_file()

    def create_results_file(self):
        """
        Create a temporary results file that can be monitored for results.
        Set a flag indicating that the file should be deleted when the process
        completes.

        """
        self.results_file_path = tempfile.NamedTemporaryFile(
            suffix='.txt', delete=False).name
        logger.debug('Creating Results File: %s', self.results_file_path)
        self._delete_results_file = True

    def delete_results_file(self):
        """If a temporary results file was created by this process, it will be
        deleted here. The results_file_path attribute is also reset to None.

        Loop for 5 seconds attempting to delete the file in case there are any
        remaining handles.

        """
        if self._delete_results_file:
            logger.debug("beginning file delete loop")
            counter = 0
            while counter <= 5:
                try:
                    os.remove(self.results_file_path)
                except PermissionError:
                    time.sleep(0.1)
                    counter += 0.1
                else:
                    logger.debug("Deleting results file: %s",
                                 self.results_file_path)
                    break
            else:
                logger.warning("Failed to delete file after 5 seconds: %s",
                               self.results_file_path)
        self.results_file_path = None
        self._delete_results_file = False


class EnhancedExecCommand(ExecCommand):
    """
    Improved version of the built-in exec command.

    Improvements:
     - Can read command results from a results file.
     - Can disable startupinfo
     - Can specify that the called process should finish before returning
     - Can specify an initial message to put in the build window

    Keyword arguments:
        Commands:
            cmd - Required if shell_cmd is empty. Overriden by shell_cmd.
                Array containing the command to run and its desired arguments.
                If you don’t specify an absolute path, the external program
                will be searched in your PATH.
            shell_cmd - Required if cmd is empty. Overrides cmd if used.
                A string that specifies the command to be run and its
                arguments.
            kill - Optional. If True, the running build will be stopped.
        Environment:
            working_dir - Optional. Directory to change the current directory
                to before running cmd. The original current directory is
                restored afterwards.
            env - Optional. Dictionary of environment variables to be merged
                with the current process’s before passing them to cmd. Use this
                option, for example, to add or modify environment variables
                without modifying your system’s settings. Environmental
                variables will be expanded.
            path - Optional. PATH used by the cmd subprocess. Use this option
                to add directories to PATH without having to modify your
                system’s settings. Environmental variables will be expanded.
            shell - Optional. If true, cmd will be run through the shell
                (cmd.exe, bash...). If shell_cmd is used, this option has no
                effect. Defaults to False.
        Results:
            file_regex - Optional. Sets the result_file_regex for the results
                view.
            line_regex - Optional. Sets the result_line_regex for the results
                view.
            encoding - Optional. Output encoding of cmd. Must be a valid Python
                encoding. Defaults to UTF-8.
            results_file_path - Optional. Path to the file containing build
                results. If not specified, a temporary file will be created
                for any command containing "<result_file>".
            quiet - Optional. Suppresses output associated with the build.
            word_wrap - Optional. Sets word wrap for the results view. Defaults
                to True.
            syntax - Optional. If provided, it will be used to colorize the
                build system’s output.

    """
    def run(self, cmd=None, shell_cmd=None, kill=False,
            working_dir="", env={},
            file_regex="", line_regex="", encoding="utf-8",
            output_panel="exec", results_file_path=None, quiet=False,
            word_wrap=True, syntax="Packages/Text/Plain text.tmLanguage",
            initial_message=None,
            # Catches "path", "shell", "startup_info", "wait"
            **kwargs):

        # clear the text_queue
        self.text_queue_lock.acquire()
        try:
            self.text_queue.clear()
            self.text_queue_proc = None
        finally:
            self.text_queue_lock.release()

        if kill:
            if self.proc:
                self.proc.kill()
                self.proc = None
                self.append_string(None, "[Cancelled]")
            return

        if not hasattr(self, 'output_view'):
            # Try not to call get_output_panel until the regexes are assigned
            self.output_view = self.window.create_output_panel(output_panel)

        # Default the to the current files directory if no working directory
        # was given
        if (working_dir == "" and self.window.active_view()
                and self.window.active_view().file_name()):
            working_dir = os.path.dirname(
                self.window.active_view().file_name())

        self.output_view.settings().set("result_file_regex", file_regex)
        self.output_view.settings().set("result_line_regex", line_regex)
        self.output_view.settings().set("result_base_dir", working_dir)
        self.output_view.settings().set("word_wrap", word_wrap)
        self.output_view.settings().set("line_numbers", False)
        self.output_view.settings().set("gutter", False)
        self.output_view.settings().set("scroll_past_end", False)
        self.output_view.assign_syntax(syntax)

        # Call create_output_panel a second time after assigning the above
        # settings, so that it'll be picked up as a result buffer
        self.window.create_output_panel(output_panel)

        self.encoding = encoding
        self.quiet = quiet

        self.proc = None
        if not self.quiet:
            if shell_cmd:
                print("Running " + shell_cmd)
            else:
                print("Running " + " ".join(cmd))
            sublime.status_message("Building")

        show_panel_on_build = sublime.load_settings(
            "Preferences.sublime-settings").get("show_panel_on_build", True)
        if show_panel_on_build and (not self.quiet):
            self.window.run_command("show_panel",
                                    {"panel": "output." + output_panel})
            if initial_message is not None:
                self.output_view.run_command('append',
                                             {'characters': initial_message,
                                              'force': True})

        merged_env = env.copy()
        if self.window.active_view():
            user_env = self.window.active_view().settings().get('build_env')
            if user_env:
                merged_env.update(user_env)

        # Change to the working dir, rather than spawning the process with it,
        # so that emitted working dir relative path names make sense
        if working_dir != "":
            os.chdir(working_dir)

        self.debug_text = ""
        if shell_cmd:
            self.debug_text += "[shell_cmd: " + shell_cmd + "]\n"
        else:
            self.debug_text += "[cmd: " + str(cmd) + "]\n"
        self.debug_text += "[dir: " + str(os.getcwd()) + "]\n"
        if "PATH" in merged_env:
            self.debug_text += "[path: " + str(merged_env["PATH"]) + "]"
        else:
            self.debug_text += "[path: " + str(os.environ["PATH"]) + "]"

        try:
            # Forward kwargs to AsyncProcess
            self.proc = EnhancedAsyncProcess(
                cmd, shell_cmd, merged_env, self, **kwargs)

            self.text_queue_lock.acquire()
            try:
                self.text_queue_proc = self.proc
            finally:
                self.text_queue_lock.release()
        except Exception as e:
            self.append_string(None, str(e) + "\n")
            self.append_string(None, self.debug_text + "\n")
            if not self.quiet:
                self.append_string(None, "[Finished]")

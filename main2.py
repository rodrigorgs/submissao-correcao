import requests # type: ignore
import os
import re
import io
import docker
from datetime import datetime
from bs4 import BeautifulSoup # type: ignore
import tempfile
import subprocess
import json
import subprocess

API_BASE_PATH = os.getenv('SUBMISSAO_API_BASE_PATH')
USERNAME = os.getenv('SUBMISSAO_USERNAME')
PASSWORD = os.getenv('SUBMISSAO_PASSWORD')
# comma-separated list of ids
CLASSROOM_ID = os.getenv('CLASSROOM_ID')
RETEST_WRONG = os.getenv('RETEST_WRONG', 'False') in ('True', 'true')

class EzSession(requests.Session):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
    
    def request(self, method, url, **kwargs):
        if (url.startswith('http')):
            return super().request(method, url, **kwargs)
        else:
            return super().request(method, self.base_url + url, **kwargs)

class EzAPI:
    def __init__(self, base_url):
        self.session = EzSession(base_url)
    
    def login(self, username, password):
        resp = self.session.post(f'login', \
            json = {
                'username': username,
                'password': password
            })

        if (resp.status_code == 200):
            token = resp.json()['access_token']
            self.session.headers.update({ 'Authorization': 'Bearer ' + token })
        else:
            raise Exception("Error on authentication")
    
    def get_assignments_with_answers(self, classroom_id):
        r = self.session.get(f'classrooms/{classroom_id}/submissions/latest')
        if (r.status_code == 200):
            return r.json()
        else:
            print(r)
            raise Exception("Error when getting answers")

    def update_score(self, submissions):
        r = self.session.put(f'submissions', json=submissions)
        if (r.status_code == 200):
            return r.json()
        else:
            print(r)
            raise Exception("Error when updating score")

class ScriptRunner:
    def __init__(self, reuse_container=True, timeout_seconds=3):
        self.timeout_seconds = timeout_seconds
        container_name = 'ezsubmission-python'
        client = docker.from_env()

        try:
            client.ping()
        except docker.errors.APIError as e:
            print(f"Error connecting to Docker daemon: {e}")
            exit(1)

        container = None
        try:
            container = client.containers.get(container_name)
            if reuse_container:
                if container.status != "running":
                    container.start()
            else:
                print('Removing existing container...')
                if container.status == "running":
                    container.stop()
                container.remove()
                container = None
        except docker.errors.NotFound:
            pass

        print('container', container)
        if container is None:
            print('Creating container...')

            container = client.containers.create(
                image='python:3.10-alpine',
                name=container_name,
                command='sleep infinity',  # Keeps the container running
                volumes={os.path.abspath("app/"): {'bind': '/app', 'mode': 'ro'}},
            )
            print('Starting container...')
            container.start()
            print('Done')
        else:
            print(f'Reusing existing container (status = {container.status})...')
            # if container is not
            if container.status == "stopped":
                container.start()
        self.container = container

    def stop(self):
        self.container.stop()
        self.container.remove(force=True)

    def run(self, code, input=''):
        if not os.path.exists('app'):
            os.makedirs('app')
        with open('app/tupy.py', 'w') as f:
            f.write('')
        with open('app/script.py', 'w') as f:
            f.write(code)
        with open('app/input.txt', 'w') as f:
            f.write(input)

        output = io.StringIO()
        res = self.container.exec_run(f'/bin/sh -c "cat /app/input.txt | timeout {self.timeout_seconds}s python /app/script.py"', stream=True, demux=False)
        for line in res.output:
            output.write(line.decode('utf-8'))
        
        return (res.exit_code, output.getvalue())

class PythonTestRunner:
    def __init__(self, script_runner):
        self.script_runner = script_runner

    def evaluate_with_testcode(self, answer, tests, extras):
        if '[[[code]]]' not in tests:
            tests = '[[[header]]]\n[[[code]]]\n[[[footer]]]' + tests;
        
        full_source = tests \
          .replace('[[[header]]]', '__print = print; print = lambda *args, **kwargs: None; __input = input; input = lambda *args, **kwargs: "3";') \
          .replace('[[[footer]]]', '\nprint = __print; input = __input\n') \
          .replace('[[[code]]]',  answer);

        exit_code, output = self.script_runner.run(full_source)
        success = output.strip() == '' or re.match('^[.]+$', output.split('\n')[0])
        return {"success": success, "output": output}

    def evaluate_with_testcases(self, answer, tests, extras):
        def transform(s):
            return s.replace('\\n', '\n').strip()
        
        cases = [c.split(']]]') for c in tests.strip().split('=====') if c.strip() != '']        
        cases = [(transform(c[0]), transform(c[1])) for c in cases]
        success_count = 0
        for test_in, test_out in cases:
            exit_code, output = self.script_runner.run(answer, test_in)
            if output.strip() == test_out.strip():
                success_count += 1
        success = success_count == len(cases)
        output = f'{success_count}/{len(cases)}'
        return {"success": success, "output": output}

class BlocompRunner:
    TIMEOUT_SECONDS = 2

    def __init__(self, assignment_url):
        self.assignment_url = assignment_url
        self.problem = self.load_problem()

    def load_problem(self):
        if m := re.match(r'.*[?]p=(.+)', self.assignment_url):
            problem_id = m.group(1)
            problem_url = f'https://rodrigorgs.github.io/blocomp/problems/{problem_id}.json'
            response = requests.get(problem_url)
            response.raise_for_status()
            return response.json()
        else:
            raise Exception('Could not find problem id in assignment URL')

    def evaluate(self, answer):
        code = json.loads(answer)["code"]["javascript"]
        if self.problem['stage']['type'] == 'cleaning':
            return self.evaluate_cleaning_robot_code(code)
        else:
            return {"success": False, "output": "test"}
    
    def evaluate_cleaning_robot_code(self, code):
        full_code = f''
        
        with open('template/cleaning_robot.js', 'r') as f:
            full_code = f.read()
        
        data_json = json.dumps(self.problem['stage']['data'])
        full_code += f'\nr = new CleaningModel({data_json})\n'
        
        code = code.replace('await window.stageManager', 'r')
        code = code.replace('window.stageManager', 'r')
        code = '\n'.join(['// ' + line if line.strip().startswith('await') else line for line in code.split('\n')])
        
        full_code += code

        full_code += 'console.log(JSON.stringify(r.outcome()))'

        tmpdirname = tempfile.mkdtemp() 
        print(tmpdirname)
        tmpfilename = os.path.join(tmpdirname, 'code.js')
        with open(tmpfilename, 'w') as f:
            f.write(full_code)
        
        output = ''
        try:
            process = subprocess.Popen(['node', tmpfilename], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            try:
                output, _ = process.communicate(timeout=BlocompRunner.TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()

            output = output.decode()

            result = json.loads(output)
            return {"success": result['successful'], "output": output}
        except Exception as e:
            print(e)
            print(output)
            return {"success": False, "output": str(e)}

        
        


# TODO: run in a container
class FlutterRunner:
    def evaluate_with_testcode(self, answer, tests, extras):
        if 'filename' not in extras:
            raise Exception('Filename not specified using the data-filename HTML attribute.')
        
        full_path = extras['filename']
        project_dir = os.path.dirname(os.path.dirname(full_path))
        script_name = os.path.basename(full_path)
        pkg_name = project_dir

        with tempfile.TemporaryDirectory() as tmpdirname:
            # copy files and folders in template/flutter_aulas to tmpdirname
            os.system(f'cp -r template/flutter_aulas {tmpdirname}/{project_dir}')

            with open(f'{tmpdirname}/{project_dir}/lib/{script_name}', 'w') as f:
                f.write(answer)
            with open(f'{tmpdirname}/{project_dir}/test/{script_name.replace(".dart", "_test.dart")}', 'w') as f:
                f.write(tests)

            # Run dart/flutter test
            dart_or_flutter_cmd = 'flutter' if extras['lang'] == 'flutter' else 'dart'
            print(f'Dart or flutter: {dart_or_flutter_cmd}')
            try:
                output = subprocess.check_output(f'cd {tmpdirname}/{project_dir} && {dart_or_flutter_cmd} test', shell=True, stderr=subprocess.STDOUT).decode()
            except subprocess.CalledProcessError as e:
                output = e.output.decode()

            #exit_code, output = self.script_runner.run(f'cd {tmpdirname} && flutter test')
        
            # success should be true if output contains 'All tests passed!'
            success = 'All tests passed!' in output
            return {"output": output, "success": success}


class AssignmentService:
    def __init__(self):
        self.assignments = {}
    
    def get_assignment(self, assignment_url):
        if (assignment_url not in self.assignments):
            self.assignments[assignment_url] = Assignment(assignment_url)
        return self.assignments[assignment_url]

def remove_elements_starting_from_element(lst, elem):
    index_of_elem = lst.index(elem) if elem in lst else -1
    if index_of_elem != -1:
        return lst[:index_of_elem]
    else:
        return lst

def next_until(soup, from_elem, until_selector):
    selected_elements = soup.select(until_selector)
    ret = []
    all_siblings = from_elem.find_next_siblings()
    for elem in all_siblings:
        if elem in selected_elements:
            break
        ret.append(elem)
    return ret

class Assignment:
    def __init__(self, assignment_url):
        self.assignment_url = assignment_url
        self.load_extras()

    def load_extras(self):
        extras = []

        r = requests.get(self.assignment_url)
        soup = BeautifulSoup(r.content, 'html5lib')
        
        for code_elem in soup.select('.code'):
            question_extra = {}
            # Get code language
            for class_name in code_elem['class']:
                if match := re.match('lang-(.*?)$', class_name):
                    question_extra['lang'] = match.group(1)
            # Get filename from data-filename
            if code_elem.has_attr('data-filename'):
                question_extra['filename'] = code_elem['data-filename']
            siblings = next_until(soup, code_elem, 'h2')
            for elem in siblings:
                class_name = ''
                if elem.has_attr('class') and len(elem['class']) > 0:
                    for class_name in elem['class']:
                        if class_name in ['testcases', 'testcode', 'runtemplate']:
                            question_extra[class_name] = {
                                'contents': elem.contents[0],
                                'type': class_name
                            }
            extras.append(question_extra)
        
        self.extras = extras

    def get_extras_for_question(self, question_index):
        return self.extras[question_index]

def main():
    service = AssignmentService()
    python_script_runner = ScriptRunner()
    api = EzAPI(API_BASE_PATH)
    SUBMISSION_BATCH_SIZE = 30
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S %z')

    api.login(USERNAME, PASSWORD)
    for classroom_id in CLASSROOM_ID.split(','):
        print(f'Evaluating classroom {classroom_id}...')
        submissions_to_update = []
        assignments = api.get_assignments_with_answers(classroom_id)
        for assignment in assignments:
            for submission in assignment['submissions']:
                if (submission['score'] is None) or (RETEST_WRONG and (submission['score'] < '1.000' or submission['score'] == '0.000')):
                    print('Evaluating submission', submission['id'], 'with question index', submission['question_index'], '... ', end='')
                    answer = submission['answer']
                    extras = service.get_assignment(assignment['assignment_url']).get_extras_for_question(submission['question_index'])
                    test_results = None
                    # use runtemplate if available
                    # if 'runtemplate' in extras:
                    #     answer = extras['runtemplate']['contents'].replace('[[[code]]]', answer);

                    if 'lang' in extras and extras['lang'] in ('flutter', 'dart'):
                        runner = FlutterRunner()
                    elif 'lang' in extras and extras['lang'] == 'blocomp':
                        runner = BlocompRunner(assignment['assignment_url'])
                    else:
                        runner = PythonTestRunner(python_script_runner)
                    
                    score = 0
                    if 'testcases' in extras:
                        test_results = runner.evaluate_with_testcases(answer, extras['testcases']['contents'], extras)
                    elif 'testcode' in extras:
                        test_results = runner.evaluate_with_testcode(answer, extras['testcode']['contents'], extras)
                    else:
                        test_results = runner.evaluate(answer)
                    if test_results['success']:
                        score = 1
                    print('score:', score)
                    submissions_to_update.append({
                        'id': submission['id'],
                        'score': score,
                        'score_timestamp': now,
                        'score_output': test_results['output']})
                    if len(submissions_to_update) >= SUBMISSION_BATCH_SIZE:
                        print('Updating score...')
                        api.update_score(submissions_to_update)
                        submissions_to_update = []
    
        print('Updating score...')
        api.update_score(submissions_to_update)

if __name__ == '__main__':
    main()
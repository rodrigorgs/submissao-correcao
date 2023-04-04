import requests # type: ignore
import os
import re
import io
import docker
from datetime import datetime
from bs4 import BeautifulSoup # type: ignore

API_BASE_PATH = os.getenv('SUBMISSAO_API_BASE_PATH')
USERNAME = os.getenv('SUBMISSAO_USERNAME')
PASSWORD = os.getenv('SUBMISSAO_PASSWORD')
CLASSROOM_ID = os.getenv('CLASSROOM_ID')

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
            if not reuse_container:
                print('Removing existing container...')
                if container.status == "running":
                    container.stop()
                container.remove()
        except docker.errors.NotFound:
            pass

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
            print('Reusing existing container...')
        self.container = container

    def stop(self):
        self.container.stop()
        self.container.remove(force=True)

    def run(self, code, input=''):
        if not os.path.exists('app'):
            os.makedirs('app')
        with open('app/script.py', 'w') as f:
            f.write(code)
        with open('app/input.txt', 'w') as f:
            f.write(input)

        output = io.StringIO()
        res = self.container.exec_run(f'/bin/sh -c "cat /app/input.txt | timeout {self.timeout_seconds}s python /app/script.py"', stream=True, demux=False)
        for line in res.output:
            output.write(line.decode('utf-8'))
        
        return (res.exit_code, output.getvalue())

class TestRunner:
    def __init__(self):
        self.script_runner = ScriptRunner()

    def evaluate_with_testcode(self, answer, tests):
        full_source = f'''
__print = print; print = lambda *args, **kwargs: None; __input = input; input = lambda *args, **kwargs: "3";
{answer}
print = __print; input = __input
{tests}
'''
        exit_code, output = self.script_runner.run(full_source)
        success = output.strip() == '' or re.match('^[.]+$', output.split('\n')[0])
        return {"success": success, "output": output}

    def evaluate_with_testcases(self, answer, tests):
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

class AssignmentService:
    def __init__(self):
        self.assignments = {}
    
    def get_assignment(self, assignment_url):
        if (assignment_url not in self.assignments):
            self.assignments[assignment_url] = Assignment(assignment_url)
        return self.assignments[assignment_url]

class Assignment:
    def __init__(self, assignment_url):
        self.assignment_url = assignment_url
        self.load_tests()

    def load_tests(self):
        ret = []
        r = requests.get(self.assignment_url)
        soup = BeautifulSoup(r.content, 'html5lib')
        for test in soup.select('.testcases, .testcode'):
            ret.append({
                'contents': test.contents[0],
                'type': test['class'][0]
            })
        self.tests = ret

    def get_test_for_question(self, question_index):
        return self.tests[question_index]

def main():
    service = AssignmentService()
    runner = TestRunner()
    api = EzAPI(API_BASE_PATH)
    SUBMISSION_BATCH_SIZE = 30
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S %z')

    api.login(USERNAME, PASSWORD)
    submissions_to_update = []
    assignments = api.get_assignments_with_answers(CLASSROOM_ID)
    for assignment in assignments:
        for submission in assignment['submissions']:
            if (submission['score'] is None):
                print('Evaluating submission', submission['id'], 'with question index', submission['question_index'], '... ', end='')
                answer = submission['answer']
                tests = service.get_assignment(assignment['assignment_url']).get_test_for_question(submission['question_index'])
                score = 0
                test_results = None
                if tests['type'] == 'testcases':
                    test_results = runner.evaluate_with_testcases(answer, tests['contents'])
                elif tests['type'] == 'testcode':
                    test_results = runner.evaluate_with_testcode(answer, tests['contents'])
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
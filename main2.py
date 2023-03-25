import requests
import os
import subprocess
from bs4 import BeautifulSoup

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
        r = self.session.get(f'classrooms/{classroom_id}/submissions')
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

class TestRunner:
    # TODO: use a single docker container to evaluate multiple answers, with a readonly filesystem
    
    def run_python(self, code):
        cmd = ['docker', 'run', '-i', '--rm', 'python:3.10-alpine', '/bin/sh', '-c', 'python', '-']
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, errors = proc.communicate(input=code)
        proc.wait()
        return proc

    def evaluate_with_testcode(self, answer, tests):
        full_source = f'{answer}\n{tests}'
        proc = self.run_python(full_source)
        return proc.returncode == 0

    # TODO: evaluate_with_testcases
    def evaluate_with_testcases(self, answer, tests):
        cases = tests.strip().split('=====')
        for case in cases:
            pass

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
            ret.append(test.contents[0])
        self.tests = ret

    def get_test_for_question(self, question_index):
        return self.tests[question_index]

def main():
    service = AssignmentService()
    runner = TestRunner()
    api = EzAPI(API_BASE_PATH)
    
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
                if runner.evaluate_with_testcode(answer, tests):
                    score = 1
                print('score:', score)
                submissions_to_update.append({ 'id': submission['id'], 'score': score })                
    
    print('Updating score...')
    api.update_score(submissions_to_update)

if __name__ == '__main__':
    main()
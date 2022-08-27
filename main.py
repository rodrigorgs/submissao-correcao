import requests
import re
import os
import subprocess
from bs4 import BeautifulSoup

API_BASE_PATH = 'https://suporteic.ufba.br/_submissao'
# API_BASE_PATH = 'http://localhost:8080'
USERNAME = os.getenv('SUBMISSAO_USERNAME')
PASSWORD = os.getenv('SUBMISSAO_PASSWORD')

class SubmissaoService:
    def __init__(self, api_base_path=None, username=None, password=None):
        self.api_base_path = api_base_path or API_BASE_PATH
        self.username = username or os.getenv('SUBMISSAO_USERNAME')
        self.password = password or os.getenv('SUBMISSAO_PASSWORD')
        self.token = None

    def login(self):
        resp = requests.post(f'{API_BASE_PATH}/login.php', \
            json = {
                'username': USERNAME,
                'password': PASSWORD
            })

        if (resp.status_code == 200):
            self.token = resp.text
        else:
            raise Exception("Erro ao fazer login")

    def get_assignments(self):
        # TODO
        pass

class AssignmentService:
    def __init__(self, assignment_url, api_base_path, token):
        self.assignment_url = assignment_url
        self.api_base_path = api_base_path
        self.token = token
        self.codes = None
        self.answers = None

    def get_code_in_textareas(self):
        if self.codes is None:
            r = requests.get(self.assignment_url)
            soup = BeautifulSoup(r.content, 'html5lib')
            ret = []
            for textarea in soup.find_all('textarea', 'code'):
                ret.append(textarea.contents[0])
            self.codes = ret
        return self.codes
    
    def get_tests(self, question_index):
        code = self.get_code_in_textareas()[question_index]
        regex = re.compile('^### Test', re.MULTILINE)
        m = regex.search(code)
        if m:
            return code[m.start():]
        else:
            return ''

    def _get_stats(self):
        resp = requests.get(f'{API_BASE_PATH}/assignment-stats.php', \
            params = {
                'url': self.assignment_url,
                'submission_type': 'batch'
            })

        if (resp.status_code == 200):
            return resp.text
        else:
            raise Exception("Erro ao consultar estatísticas")

    def get_submitters(self):
        csv = self._get_stats()
        rows = [line.split('\t') for line in csv.strip().split("\n")]
        return [row[0] for row in rows[1:]]
        # resp = requests.get(f'{API_BASE_PATH}/assignment-stats.php', \
        #     params = {
        #         'url': self.assignment_url,
        #         'submission_type': 'batch'
        #     })

        # if (resp.status_code == 200):
        # else:
        #     raise Exception("Erro ao consultar estatísticas")

    def get_number_of_questions(self):
        csv = self._get_stats()
        return len(csv.split('\n')[0].split('\t')) - 2

    def get_answers(self, username):
        if self.answers is None:
            r = requests.post(f'{self.api_base_path}/get-answers.php', \
                headers = {
                    'Authorization': 'Bearer ' + self.token
                },
                json = {
                    'assignment_url': self.assignment_url,
                    'username': username,
                    'submission_type': 'batch'
                })
            if r.status_code != 200:
                raise Exception("Erro ao obter resposta:", username)
            self.answers = r.json()
        return self.answers
    
    def evaluate(self, answer, question_index):
        '''
        Return True if the answer passes the tests, false otherwise
        '''
        # answer = self.get_answers(username)[question_index]
        answer += '\n' + self.get_tests(question_index)
        cmd = ['docker', 'run', '-i', '--rm', 'python:3.10-alpine', '/bin/sh', '-c', 'python', '-']
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, errors = proc.communicate(input=answer)
        proc.wait()
        return proc.returncode == 0

    def evaluate_all(self):
        result = {}
        usernames = [x for x in self.get_submitters() if len(x) > 0]
        n_questions = self.get_number_of_questions()
        for username in usernames:
            scores = []
            answers = self.get_answers(username)
            for question_index in range(n_questions):
                evaluation = self.evaluate(answers[question_index], question_index)
                scores.append(evaluation)
                print(username, question_index, evaluation)
            result[username] = scores
        return result

sub = SubmissaoService()
sub.login()
# ass = AssignmentService('http://localhost:4000/aulas/poo/ex-python-intro', sub.api_base_path, sub.token)
ass = AssignmentService('https://rodrigorgs.github.io/aulas/poo/ex-python-intro', sub.api_base_path, sub.token)
print(ass.evaluate_all())

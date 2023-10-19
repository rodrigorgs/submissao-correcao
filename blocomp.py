import re
import requests
import json
import subprocess
import tempfile
import os
import traceback

class BlocompRunner:
    TIMEOUT_SECONDS = 2

    def __init__(self, assignment_url):
        self.assignment_url = assignment_url
        self.problem = self.load_problem()
        self.problem_type = self.problem.get('stage', {}).get('type', None)

    def load_problem(self):
        if m := re.match(r'(.*)[?]p=(.+)', self.assignment_url):
            prefix = m.group(1)
            problem_id = m.group(2)
            problem_url = f'{prefix}problems/{problem_id}.json'
            response = requests.get(problem_url)
            response.raise_for_status()
            return response.json()
        else:
            raise Exception('Could not find problem id in assignment URL')

    def evaluate(self, answer):
        if not 'testCases' in self.problem["problem"]:
            self.problem["problem"]["testCases"] = [{"input": ""}]
        
        total = len(self.problem["problem"]["testCases"])
        correct = 0
        output = ''
        for test_case in self.problem["problem"]["testCases"]:
            result = self.evaluate_robot_with_testcase(answer, test_case)
            if result is not None and 'output' in result:
                output += str(result["output"])
            if result is not None and 'success' in result and result["success"]:
                correct += 1
            else:
                break
        return {"success": correct == total, "output": output}
    
    def transform_code(self, code, data=None, problem_type=None):
        full_code = '''
const readline = require('readline');

const _readlineInterface = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});
const _readlineIterator = _readlineInterface[Symbol.asyncIterator]();

async function prompt() {
    return (await _readlineIterator.next()).value;
}

'''   
        if self.problem_type == 'cleaning':
            with open('template/cleaning_robot.js', 'r') as f:
                full_code += f.read()
        
        if data is None:
            data = self.problem['stage']['data']
        data_json = json.dumps(data)
        
        full_code += 'async function main() {\n'
        if self.problem_type == 'cleaning':
            full_code += f'\n_cleaningModel = new CleaningModel({data_json})\n'
        
        code = re.sub(r"^.*window.chatManager.addMessage.*Digite um .* para guardar como.*$", "", code, flags=re.MULTILINE)
        code = re.sub(r"window.chatManager.addMessage[(](.+), 'received'[)];", r"console.log(\1);", code);
        code = code.replace('prompt(', 'await prompt(')
        code = code.replace('await window.stageManager', '_cleaningModel')
        code = code.replace('window.stageManager', '_cleaningModel')
        code = code.replace('window.chatManager', '// window.chatManager')
        code = '\n'.join(['// ' + line if line.strip().startswith('await') else line for line in code.split('\n')])
        
        full_code += code

        if self.problem_type == 'cleaning':
            full_code += 'console.log("\\n");'
            full_code += 'console.log(JSON.stringify(_cleaningModel.outcome()));'

        full_code += '\n_readlineInterface.close();\n} \n main();'

        return full_code

    def evaluate_robot_with_testcase(self, answer, testcase):
        code = json.loads(answer)["code"]["javascript"]
        input_string = testcase.get('input', '') + '\n'
        
        data = self.problem.get('stage', {}).get('data', {})
        if 'data' in testcase:
            data = testcase['data']

        full_code = self.transform_code(code, data)

        tmpdirname = tempfile.mkdtemp() 
        print(tmpdirname)
        tmpfilename = os.path.join(tmpdirname, 'code.js')
        with open(tmpfilename, 'w') as f:
            f.write(full_code)
        
        output = ''
        try:
            env = os.environ.copy()
            cwd = os.path.dirname(__file__)
            env['NODE_PATH'] = os.path.join(cwd, 'node_modules') + ':' + env.get('NODE_PATH', '')
            process = subprocess.Popen(['node', tmpfilename], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd)

            try:
                output, _ = process.communicate(input=input_string.encode(), timeout=BlocompRunner.TIMEOUT_SECONDS)

                if self.problem_type == 'cleaning':
                    json_string = output.decode().strip().split("\n")[-1]
                    result = json.loads(json_string)
                    success = result['successful']
                    if testcase.get('output', None) is not None:
                        relevant_output = '\n'.join(output.decode().strip().split("\n")[:-1]).strip()
                        success = success and relevant_output == testcase['output'].strip()
                    return {"success": success, "output": output}
                else:
                    success = output.decode().strip() == testcase.get('output', '').strip()
                    print({"success": success, "output": output.decode()})
                    return {"success": success, "output": output.decode()}
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
            
        except Exception as e:
            print(traceback.format_exc())
            print('json_string:', json_string)
            return {"success": False, "output": str(e)}

    def evaluate_cleaning_robot_code(self, code):
        full_code = self.transform_code(code)

        tmpdirname = tempfile.mkdtemp() 
        print(tmpdirname)
        tmpfilename = os.path.join(tmpdirname, 'code.js')
        with open(tmpfilename, 'w') as f:
            f.write(full_code)
        
        output = ''
        try:
            env = os.environ.copy()
            cwd = os.path.dirname(__file__)
            env['NODE_PATH'] = os.path.join(cwd, 'node_modules') + ':' + env.get('NODE_PATH', '')
            process = subprocess.Popen(['node', tmpfilename], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd)

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
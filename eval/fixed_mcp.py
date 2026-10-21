"""평가용 고정 MCP. 도구 호출 대상과 호출마다 바뀌는 수치를 기록한다."""
class MonitoringMCP:
    def __init__(self): self.calls = []
    async def start(self): pass
    async def stop(self): pass
    async def find_prompt(self, *args): return 'ops'
    async def get_prompt(self, *args, **kwargs): return '모니터링과 대응 절차를 확인하세요.'
    async def find_resource_template(self, *args): return 'ops', 'runbook://incident-response/{incident_type}'
    async def read_resource(self, *args, **kwargs): return '# CPU 대응\n1. 상태 확인\n2. 로그 확인 권장\n3. 추가 조사'
    async def call_tool(self, name, arguments):
        self.calls.append(arguments['system_name'])
        return {'system_name': arguments['system_name'], 'status': 'degraded',
                'cpu_percent': 70 + len(self.calls), 'memory_percent': 50,
                'alerts': ['CPU high']}

"""Layer rules and pipeline plug-in contracts. Synthetic inputs only; no device is used."""
import ast
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from scout_mobile.architecture import ALLOWED_UPWARD, LAYER_OF, LAYERS
from scout_mobile.engine import NEXT_STEP, Node, Pipeline, PipelineError, build_pipeline, default_pipeline

PACKAGE=Path(__file__).resolve().parents[1]/'scout_mobile'


def top_level(path:Path)->str:
    return path.relative_to(PACKAGE).parts[0].removesuffix('.py')


def imported_modules(path:Path)->set[str]:
    """Top-level scout_mobile modules imported anywhere in a file, including inside functions."""
    package=list(path.relative_to(PACKAGE).parent.parts)
    found=set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node,ast.ImportFrom):
            if node.level:
                base=package[:len(package)-(node.level-1)] if node.level>1 else package
                parts=base+(node.module.split('.') if node.module else [])
                if parts:found.add(parts[0])
                else:found.update(alias.name for alias in node.names)
            elif node.module and node.module.split('.')[0]=='scout_mobile':
                parts=node.module.split('.')[1:]
                if parts:found.add(parts[0])
                else:found.update(alias.name for alias in node.names)
        elif isinstance(node,ast.Import):
            for alias in node.names:
                parts=alias.name.split('.')
                if parts[0]=='scout_mobile' and len(parts)>1:found.add(parts[1])
    return found


class LayerTests(unittest.TestCase):
    def test_every_module_has_a_layer(self):
        modules={top_level(path) for path in PACKAGE.rglob('*.py')}
        self.assertEqual(sorted(modules-set(LAYER_OF)),[],'Assign new modules a layer in scout_mobile/architecture.py.')

    def test_imports_only_point_down(self):
        violations=[]
        for path in sorted(PACKAGE.rglob('*.py')):
            source=top_level(path)
            for target in imported_modules(path):
                if target==source or target not in LAYER_OF:continue
                if LAYER_OF[target]>LAYER_OF[source] and (source,target) not in ALLOWED_UPWARD:
                    violations.append(f'{path.relative_to(PACKAGE)}: {source} ({LAYERS[LAYER_OF[source]][0]}) imports {target} ({LAYERS[LAYER_OF[target]][0]})')
        self.assertEqual(violations,[])


class Marker(Node):
    name='marker';role='verification'
    summary='Synthetic plugin node.'
    def __init__(self):self.calls=[]
    def run(self,ctx):self.calls.append(ctx.step)


class PipelineEditingTests(unittest.TestCase):
    def test_default_pipeline_is_valid_and_ordered(self):
        pipeline=default_pipeline();pipeline.validate()
        step=[node.name for node in pipeline.nodes('step')]
        self.assertLess(step.index('decide'),step.index('consent_guard'))
        self.assertLess(step.index('consequential_control_guard'),step.index('perform_action'))
        self.assertLess(step.index('ground_target'),step.index('perform_action'))
        self.assertEqual([node.name for node in pipeline.nodes('teardown')][-1],'device_lease_release')
        names=[node.name for node in pipeline.nodes()]
        self.assertEqual(len(names),len(set(names)))

    def test_locked_safety_nodes_cannot_be_removed_or_replaced(self):
        pipeline=default_pipeline()
        for name in ('consent_guard','consequential_control_guard','resolve_text','credential_prompt','device_lease'):
            with self.subTest(name=name):
                self.assertTrue(pipeline.get(name).locked)
                with self.assertRaises(PipelineError):pipeline.remove(name)
                with self.assertRaises(PipelineError):pipeline.replace(name,Marker())

    def test_unlocked_nodes_can_be_plugged_in_and_out(self):
        pipeline=default_pipeline()
        pipeline.remove('cycle_detector').insert(Marker(),after='settle')
        step=[node.name for node in pipeline.nodes('step')]
        self.assertNotIn('cycle_detector',step)
        self.assertEqual(step[step.index('settle')+1],'marker')
        with self.assertRaises(PipelineError):pipeline.insert(Marker(),after='settle')

    def test_missing_requirements_fail_closed(self):
        class NeedsDecision(Node):
            name='early';role='guard';requires=('decision',)
            def run(self,ctx):pass
        pipeline=default_pipeline().insert(NeedsDecision(),before='decide')
        with self.assertRaisesRegex(PipelineError,'requires decision'):pipeline.validate()

    def test_decision_agent_slot_is_replaceable(self):
        class Scripted(Node):
            name='decide';role='decision';provides=('decision','op','selected','public','loop_started')
            def run(self,ctx):pass
        pipeline=default_pipeline().replace('decide',Scripted())
        pipeline.validate()
        self.assertEqual(pipeline.get('decide').describe()['source'].split(':')[1],'PipelineEditingTests.test_decision_agent_slot_is_replaceable.<locals>.Scripted')

    def test_env_plugins_and_disabled_nodes(self):
        plugin=ModuleType('scout_synthetic_plugin');plugin.install=install_marker
        sys.modules['scout_synthetic_plugin']=plugin;self.addCleanup(sys.modules.pop,'scout_synthetic_plugin',None)
        with patch.dict(os.environ,{'SCOUT_PIPELINE_PLUGINS':'scout_synthetic_plugin:install','SCOUT_DISABLED_NODES':'date_gate'}):
            pipeline=build_pipeline()
        self.assertIn('marker',pipeline)
        self.assertNotIn('date_gate',pipeline)
        with patch.dict(os.environ,{'SCOUT_DISABLED_NODES':'consent_guard'}),self.assertRaises(PipelineError):
            build_pipeline()
        with patch.dict(os.environ,{'SCOUT_PIPELINE_PLUGINS':'scout_synthetic_plugin:missing'}),self.assertRaises(PipelineError):
            build_pipeline()

    def test_node_returning_unexpected_value_is_an_error(self):
        class Bad(Node):
            name='bad';stage='setup';role='guard'
            def run(self,ctx):return 'oops'
        pipeline=Pipeline([Bad()])
        ctx=SimpleNamespace(step=0,trace=[],agent=None)
        with self.assertRaises(PipelineError):next(pipeline.run(ctx))
        self.assertEqual(ctx.trace[-1]['outcome'],'error:PipelineError')


def install_marker(pipeline):
    pipeline.insert(Marker(),after='settle')


class PluginRunTests(unittest.TestCase):
    def setUp(self):
        backend=patch.dict(os.environ,{'SCOUT_ANDROID_DRIVER':'adb'})
        backend.start();self.addCleanup(backend.stop)

    def test_plugin_node_runs_each_step_and_run_writes_node_trace(self):
        from scout_mobile.agent import Agent,RunConfig
        from scout_mobile.device import Element,Screen
        button=Element('1','button','Next','','Button','',(10,10,200,60),('TAP',),False)
        first=Screen('',[button],'Welcome · Next','first',1080,2340)
        second=Screen('',[],'All set','second',1080,2340)
        fake=Mock();fake.installed.return_value=True;fake.wait_for_content.return_value=first
        fake.foreground.return_value='example.app';fake.observe.side_effect=[first,second]
        fake.wait_for_change.return_value=second
        fake.command.return_value=SimpleNamespace(stdout=b'')
        fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
        tap={'operation':'TAP','target':'1','confidence':1,'model':'test','latency_ms':1,'jev':{}}
        done={'operation':'DONE','target':None,'confidence':1,'model':'test','latency_ms':1,'jev':{}}
        marker=Marker()
        with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=[tap,done]),\
             patch('scout_mobile.agent.build_pipeline',side_effect=lambda:default_pipeline().insert(marker,after='settle')):
            result=Agent(RunConfig('example.app','fake',{'goal':'Reach the end'},Path(directory),expected_text='All set')).run()
            report=json.loads((Path(directory)/'pipeline.json').read_text())
        self.assertEqual(result['status'],'Passed')
        self.assertEqual(marker.calls,[1])
        self.assertIn('marker',[node['name'] for node in report['nodes']['step']])
        step_one=[(item['node'],item['outcome']) for item in report['trace'] if item['step']==1]
        self.assertIn(('perform_action','next'),step_one)
        self.assertIn(('marker','next'),step_one)
        self.assertEqual([item for item in report['trace'] if item['step']==2][-1]['node'],'done')
        # pipeline_report writes the file, so its own entry and the lease release come after it.
        self.assertEqual(report['trace'][-1]['node'],'device_close')
        fake.tap.assert_called_once_with(button)


if __name__=='__main__':unittest.main()

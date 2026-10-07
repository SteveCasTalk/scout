"""Jev and LLM decision agents share options and validation. Synthetic screens; no model is called."""
import json
import os
import unittest
from unittest.mock import patch
from scout_mobile.device import Element
from scout_mobile.engine import PipelineError, build_pipeline
from scout_mobile.engine.nodes.decide import JevDecision, LLMDecision
from scout_mobile.model import ModelError, choose_llm, decision_options

NEXT=Element('1','button','Next','','Button','',(10,10,200,60),('TAP',),False)
NAME=Element('2','textbox','Name','','EditText','',(10,70,200,120),('TYPE_TEXT',),False)
ENV={'TEXT_MODEL_API_KEY':'test-key','TEXT_MODEL_BASE_URL':'https://llm.invalid/v1','TEXT_MODEL':'test-chat'}


def reply(answer):
    return {'model':'test-chat','choices':[{'message':{'content':json.dumps(answer)}}],'usage':{'total_tokens':42}}


class LLMDecisionTests(unittest.TestCase):
    def call(self,answer):
        with patch.dict(os.environ,ENV),patch('scout_mobile.model.post_json',return_value=reply(answer)) as post:
            return choose_llm([NEXT,NAME],'Welcome · Next','Continue',[]),post

    def test_valid_choice_has_the_jev_decision_shape(self):
        decision,post=self.call({'operation':'TAP','target':1,'confidence':0.8})
        self.assertEqual((decision['operation'],decision['target'],decision['confidence']),('TAP','1',0.8))
        self.assertEqual(decision['model'],'test-chat')
        self.assertEqual(decision['jev']['agent'],'llm')
        self.assertEqual(post.call_args.args[0],'https://llm.invalid/v1/chat/completions')

    def test_llm_sees_the_same_operations_and_targets_as_jev(self):
        _,post=self.call({'operation':'DONE','target':None,'confidence':0.9})
        prompt=json.loads(post.call_args.args[2]['messages'][1]['content'])
        operations,targets,_,_=decision_options([NEXT,NAME],'Welcome · Next','Continue',[])
        self.assertEqual(prompt['operations'],operations)
        self.assertEqual(set(prompt['tap_targets']),set(targets['TAP']))
        self.assertEqual(set(prompt['type_text_targets']),set(targets['TYPE_TEXT']))

    def test_non_target_operations_drop_any_target(self):
        decision,_=self.call({'operation':'SWIPE_UP','target':'1','confidence':0.5})
        self.assertIsNone(decision['target'])

    def test_invalid_choices_are_rejected_without_acting(self):
        for answer in ({'operation':'PURCHASE','target':None,'confidence':1},
                       {'operation':'TAP','target':'9','confidence':1},
                       {'operation':'TAP','target':'2','confidence':1},  # field, not a tap target
                       {'operation':'TAP','target':'1','confidence':3}):
            with self.subTest(answer=answer),self.assertRaises(ModelError):self.call(answer)
        with patch.dict(os.environ,ENV),patch('scout_mobile.model.post_json',return_value={'choices':[{'message':{'content':'not json'}}]}):
            with self.assertRaises(ModelError):choose_llm([NEXT],'Next','Continue',[])

    def test_missing_key_fails_closed(self):
        with patch.dict(os.environ,{'TEXT_MODEL_API_KEY':''}),patch('scout_mobile.model.getenv',side_effect=lambda name,default=None:'' if name=='TEXT_MODEL_API_KEY' else default):
            with self.assertRaises(ModelError):choose_llm([NEXT],'Next','Continue',[])


class DecisionAgentSelectionTests(unittest.TestCase):
    def test_default_is_jev_and_llm_is_selectable(self):
        with patch.dict(os.environ,{'SCOUT_DECISION_AGENT':''}):
            self.assertIs(type(build_pipeline().get('decide')),JevDecision)
        with patch.dict(os.environ,{'SCOUT_DECISION_AGENT':'llm'}):
            self.assertIs(type(build_pipeline().get('decide')),LLMDecision)
        with patch.dict(os.environ,{'SCOUT_DECISION_AGENT':'other'}),self.assertRaises(PipelineError):
            build_pipeline()


if __name__=='__main__':unittest.main()

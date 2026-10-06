"""Deterministic interpretation of timestamped UI samples; no inferred continuity."""
class TemporalState:
    def __init__(self,rule,trigger_ms):
        self.rule=rule;self.trigger=trigger_ms;self.deadline=trigger_ms+rule['window_ms']
        self.last=trigger_ms;self.good=True;self.order=0;self.count=0;self.done=False;self.verdict='not_observable';self.reason='Observation window incomplete.'
    def finish(self,verdict,reason):
        self.done=True;self.verdict=verdict;self.reason=reason
        if self.rule['evidence']=='continuous_events' and verdict!='violated':
            self.verdict='not_observable';self.reason='No complete instrumented event source was supplied; sampled UI is insufficient.'
    def feed(self,start_ms,end_ms,context,predicate,terminal=False,hits=()):
        if self.done:return
        rule=self.rule;self.count+=1
        self.good=self.good and context and end_ms-self.last<=rule['max_gap_ms']
        self.last=end_ms
        if context and rule['mode']=='within' and predicate and end_ms<=self.deadline:
            self.finish('satisfied','Predicate observed within the event-relative deadline.');return
        if context and end_ms<=self.deadline:
            if rule['mode']=='never_during' and predicate:
                self.finish('violated','Forbidden predicate directly observed during the interval.');return
            if rule['mode'] in {'stable_for','until'} and not predicate and not terminal:
                self.finish('violated','Required predicate directly absent on its applicable observed screen.');return
            if rule['mode']=='ordered':
                new=[i for i in hits if i>=self.order]
                if len(new)>1:self.good=False
                elif new:
                    if new[0]!=self.order:self.finish('violated','Predicates observed out of order.');return
                    self.order+=1
                    if self.order==len(rule['ordered_texts']) and end_ms<=self.deadline and self.good:
                        self.finish('satisfied','Ordered predicates established in distinct observations.');return
            if rule['mode']=='until' and terminal:
                self.finish('satisfied' if self.good else 'not_observable','Sampled requirement held through the terminal state.' if self.good else 'Observation gap prevents establishing the until requirement.');return
        if end_ms>=self.deadline:
            if rule['mode']=='stable_for' and self.good and self.count>=2:
                self.finish('satisfied','Sampled stability established within the declared maximum observation gap.')
            elif rule['mode']=='never_during':
                self.finish('not_observable','UI sampling cannot establish continuous absence between observations.')
            else:self.finish('not_observable','Deadline, ordering, context, or observation coverage could not be established.')
    def result(self):
        return {'id':self.rule['id'],'required':self.rule['required'],'verdict':self.verdict,'reason':self.reason,'evidence_source':'sampled_ui','trigger_ms':self.trigger,'deadline_ms':self.deadline,'samples':self.count,'coverage_complete':self.done and self.good}

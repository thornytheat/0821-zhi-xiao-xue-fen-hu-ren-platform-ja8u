import {element} from './client.js';

function block(target,className,content) {
  const node=element('div',content,{class:className});
  target.append(node);
  return node;
}
const note=(target,text)=>block(target,'chart-note',text);

export function visualize(report,selected) {
  const target=document.querySelector('#visual');
  target.replaceChildren();
  const measurement=report.cases?.find(row=>row.case===selected)?.measure;
  if (!measurement) {block(target,'chart-note','选择有计算值的分组');return;}
  const e=measurement.evidence;

  const pairs = block(target,'credit-pairs');
  for (const [course,local] of Object.entries(e.matched)) {
    const row=block(pairs,'credit-link');
    block(row,'course',`外校 ${course}`); block(row,'join','→'); block(row,'course',`校内 ${local}`);
  }
  if (e.unmet.length) note(target,`待抵扣 ${e.unmet.join('、')}`);
}

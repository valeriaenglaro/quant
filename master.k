/ master.k - ngn/k autocallable / reverse-convertible pricer (golfed build)
/ Names are 1-2 chars; the long-name twin is master_readable.k (same output,
/ byte-for-byte - see golf_report.md). Reads json.json, prints one JSON blob.
/ Quick legend: C=100.0  Y=365.0  E=days  N=notional  R=rate  n=paths
/               T=terminal basket levels  Rf=basket path matrix  W=risk flag

/ -- config: J=payload, G pulls a string key, F is the empty-safe float cast
C:100.0;Y:365.0;J:`j?1:"json.json";pj:J@`platform;tj:J@`data;cj:J@`$"coupon_config";AC:J@`Autocall;aj:J@`$"Autocall_Coupon";G:{[d;k]d@`$k};F:{$[(@x)~`C;$[0=#x;0.0;`f$. x];`f$x]};so:G[pj;"Solve for"];rf2:F G[pj;"Reoffer (%)"]
mg:F pj@`$"Issuer Margin (%)";un:G[tj;"Underlying"];SP:`f$G[tj;"Spot Price"];nU:#un;w:G[tj;"Basket Type"];N:`f$G[tj;"Notional"];E:`i$G[tj;"Days"];dt:1.0%Y;sd:%dt;vo:`f$G[tj;"Volatility"];be:`f$G[tj;"Skew Beta"]
R:`f$G[tj;"Risk-Free Rate"];ba:G[tj;"Barrier Type"];k0:F G[tj;"KI Barrier (%)"];p0:F G[tj;"Put Strike (%)"];le:G[tj;"Leverage (%)"];on:G[tj;"One Star"];ol:F G[tj;"One Star Level (%)"];cg:G[tj;"Capital Guaranteed"];dj:G[tj;"Dividends"]
gv:$[^gg:J@`$"Capital Guarantee Level (%)";C;F gg];n:`i$J@`$"n_sims";sm:$[|/(`$"spot_mult")=!J;(nU#1.0)*`f$J@`$"spot_mult";nU#1.0];vd:$[|/(`$"vol_add")=!J;`f$J@`$"vol_add";0.0];rd2:$[|/(`$"rf_add")=!J;`f$J@`$"rf_add";0.0];R:R+rd2;sp:SP*sm

/ -- product-mode flags + dividend tables (per-underlying index/amount/day)
ia2:(ba~"American Daily Close")|ba~"American Intraday";ip:ia2|~(AC@`Type)~"None";at:aj@`$"Autocall Coupon Type";ac2:~at~"None";di:`i${x@`$"underlying_idx"}'dj;dm:`f${x@`amount}'dj

/ -- qf: dividend pv -> flat yield; qm..qn: shared Lehmer LCG + Box-Muller
/    (bit-identical to engine.py's _QSRng, so both engines draw the same paths)
dy:`f${x@`$"days_to_pay"}'dj;qf:{[i]pv:+/(di=i)*dm*`exp[-R*dy%Y];$[pv>0;(-`ln 1.0-pv%qP[i])%(E%Y);0.0]};qm:2147483647;qb:65536;qp:1_qb{qm!x*48271}\1;qt:42;qk:{[k]b:qm!qt*k#qp;qt::*|b;b};qz:{[m]f:`i$_m%qb;r:m-f*qb;(f#qb),$[r>0;,r;!0]}
qu:{[m](`f$,/qk'qz m)%qm};qn:{[m]u1:qu m;u2:qu m;(%-2.0*`ln u1)*`cos[6.283185307179586*u2]};hZ:(@J@`$"_Z")~`A;Z0:$[hZ;{(#x;#*x)#,/`f$'x}'J@`$"_Z";{(n;E)#qn n*E}'!nU]

/ -- simulation: st2 = one local-vol step, sP path-dependent / sE European;
/    SS regenerates globals A0/M0/Rf/T/rm/mx for a given spot/vol/q set
st2:{[s;zt]cv:0.05|1.20&vB-b0*s;s*`exp[((rq-0.5*cv*cv)*dt)+cv*zt*sd]};sP:{[i]+(,(n#S0)),(n#S0)st2\+Z0[i]};sE:{[i]ex:((rq-0.5*V*V)*dt)+V*(%dt)*Z0[i];cs:+\'ex;S0,'S0*`exp cs}
sA:{[i]V::gV[i];B::be[i];S0::gS[i];Q::gQ[i];vB::V+B;b0::B%S0;rq::R-Q;$[ip;sP i;sE i]};mA:{[sv;vv;qv]gS::sv;gV::vv;gQ::qv;sA'!nU};nk:{(A0[x]%SP[x])*C}
SS:{[sv;vv;qv]A0::mA[sv;vv;qv];M0::nk'!nU;Rf::$[(nU=1)|w~"None";M0 0;w~"Worst-Of";&/M0;(+/M0)%nU];T::Rf[;E];rm::&/'Rf;mx::|/{M0[x][;E]}'!nU}

/ base paths (spot_mult / vol_add overrides applied here)
qP:sp;qy:qf'!nU;SS[sp;vo+vd;qy]

/ -- schedules: br2 = banker's rounding, ob = autocall observation days
fq:{$[x~"Monthly";12;x~"Quarterly";4;x~"SemiAnnually";2;x~"Yearly";1;1]};br2:{f:`i$_x;d:x-f;$[d<0.5;f;d>0.5;f+1;0=2!f;f;f+1]};cf:fq cj@`$"Coupon Frequency";im:(cj@`$"Coupon Frequency")~"At Maturity";np2:$[im;1;`i$br2 (E%Y)*cf];ct:cj@`$"Coupon Type"
bD:`M`Q`S`Y!30 90 180 365;af:G[AC;"Autocallable From"];fd:(*bD@`$1#af)*(-1+`i$. 1_af);ax:fq AC@`$"Autocall Frequency";au2:`i$br2 (E%Y)*ax;oa:br2'((1.0+!au2)%au2)*E;ob:$[au2<1;!0;oa@&~oa<fd];oi:!#ob;op:+(oi;ob)

/ -- autocall leg: aL folds as2 over (index;day) pairs op -> (mt;called;cpn)
bf:{[i]$[ay~"Variable Barrier";(*ab)+i*sv2;ay~"Custom Barrier";ab[i];*ab]};cf2:{[i]$[a2~"Snowball";(ap%ax)*(i+1)*N;a2~"Flat";ap*N;0.0]}
as2:{[st;ij]i:ij 0;d2:ij 1;cl:(~st 1)&~Rf[;d2]<bf i;((cl*d2)+(~cl)*st 0;(st 1)|cl;(st 2)+cl*(cf2 i)*`exp[-R*d2%Y])};ae:{[P]ay::AC@`Type;sv2::F G[AC;"Step Up / Down (%)"];ab::P`acb;ap::(P`acc)%C;a2::at}
aL:{[P]s0:(n#`f$E;n#0b;n#0.0);$[(AC@`Type)~"None";s0;[ae P;$[(ay~"Issuer Callable")|0=#ob;s0;s0 as2/ op]]]};AB:{$[w~"Equally Weighted";~((+/{(A0[x][;cx]%SP[x])*C}'!nU)%nU)<cb2;&/{~A0[x][;cx]<SP[x]*cb2%C}'!nU]}

/ -- periodic coupon leg: cs2/cw2 fold pays into st; cm=at-maturity,
/    cu=fixed unconditional, cd=conditional(+memory); cV picks the branch
cs2:{[st;i]m2:(st 1)+pc;y2:(AB[])&~D>MT;((st 0)+(y2*m2)*`exp[-R*D%Y];$[ct~"Conditional with Memory";(~y2)*m2;ct~"Conditional without Memory";n#0.0;m2])};cw2:{[st;i]D::`i$_$[ye;(i%cf)*Y;(i%np2)*E];cx::E&D;cs2[st;i]};cm:{[c](MT=E)*((c%C)*(E%Y)*N)*`exp[-R*E%Y]};fo:{[d](~d>MT)*pc*`exp[-R*d%Y]}
cu:{[c]pc::((c%C)%cf)*N;$[ye;n#pc*+/`exp[-R*(1.0+!np2)%cf];[fu::`i$_((1.0+!np2)%np2)*E;$[np2<1;n#0.0;+/fo'fu]]]};cd:{[c;cb]pc::$[im;((c%C)*E%Y)*N;((c%C)%cf)*N];cb2::cb;*(n#0.0;n#0.0)cw2/(1+!np2)}
cV:{[P;mt]MT::mt;c:P`c;$[ct~"None";n#0.0;im&ct~"Fixed Unconditional";cm c;ct~"Fixed Unconditional";cu c;cd[c;P`cb]]};cL:{[P;mt](+/cV[P;mt])%n};bg:$[ba~"American Intraday";`exp[0.5826*(*vo)*%dt];1.0];bR:{[ki]k2:ki*bg;$[ba~"European (Maturity)";~T>k2;ba~"None";n#1b;~rm>k2]};ye:(AC@`Type)~"None";kR:{[ki]k2:ki*bg;$[ye;$[ba~"None";T<qo`putk;(ba~"American Daily Close")|ba~"American Intraday";~rm>k2;~T>k2];$[(ba~"European (Maturity)")|ba~"None";T<k2;rm<k2]]}

/ -- put leg pV: barrier test bR, leverage lf, one-star & called exclusions
lf:{[u3]$[le~"Yes";C%u3;le~"No";1.0;(F le)%C]};pV:{[P;ia]$[cg~"Yes";n#0.0;[ki:P`ki;u3:P`putk;br:bR ki;br:$[on~"Yes";br&mx<ol;br];br:br&~ia;w2:0.0|u3-T;(br*w2*N%C)*(lf u3)*`exp[-R*E%Y]]]};pL:{[P;ia](+/pV[P;ia])%n}

/ -- bond redemption bV (capital-guarantee cap) and total price pp
bV:{[mt;ia]N*`exp[-R*mt%Y]};pp:{[P]a:aL[P];mt:a 0;ia:a 1;a3:(+/a 2)%n;o2:(+/bV[mt;ia])%n;o2+(cL[P;mt])+a3-pL[P;ia]};b2:F G[AC;"Autocall Barrier (%)"]

/ -- parameter dict pb; pw reprices with one key swapped; sk = solve target
pb:`c`cb`ki`putk`acb`acc!(F cj@`$"Coupon (%)";F cj@`$"Coupon Barrier Level (%)";k0;p0;b2;F aj@`$"AC Coupon (%)");pw:{[k;x]Q:pb;Q[k]:x;pp[Q]}
sk:$[so~"Coupon (%)";`c;so~"KI Barrier (%)";`ki;so~"Coupon Barrier Level (%)";`cb;so~"Put Strike (%)";`putk;so~"Autocall Coupon (%)";`acc;so~"Autocall Barrier (%)";`acb;`none]

/ -- solver: secant/bisection to tolerance tl; sb flips to 0 if no bracket
tl:1e-7;sb:1;bs2:{[l;h;fl;fh]d:fh-fl;sx:$[0.0=d;.5*l+h;h-fh*(h-l)%d];$[(sx>l)&sx<h;sx;0.5*l+h]};bp:{[o]l:o 0;h:o 1;fl:o 2;fh:o 3;$[(h-l)<tl;o;[sx:bs2[l;h;fl;fh];fs:(pw[sg;sx])-tg;$[(0.0<fs)~0.0<fl;(sx;h;fs;fh);(l;sx;fl;fs)]]]}
sw:{[k;t3;lo;hi]sg::k;tg::t3;fl:(pw[k;lo])-t3;fh:(pw[k;hi])-t3;$[(0.0<fl)~0.0<fh;[sb::0;$[(fl*fl)<fh*fh;lo;hi]];(bp/(lo;hi;fl;fh))0]};sR:{[]t3:N*(rf2-mg)%C;sv:sw[sk;t3;0.0001;200.0];q:pb;q[sk]:sv;`PV`Solved!(C*(pp[q])%N;sv)}

/ -- headline result rs; greeks flag gates: W legs+risk, g2 basket, dl per-asset
pR:{[]px:C*(pp[pb])%N;`PV`Solved!(px;px+mg)};rs:$[so~"Reoffer (%)";pR[];sR[]];gk2:$[^gk:J@`greeks;0;`i$F gk];W:gk2>0;g2:gk2>1;dl:gk2>2;qo:pb;qo:$[sk~`none;qo;@[qo;sk;:;rs`Solved]];pf2:{[]C*(pp[qo])%N};pv2:C*(pp[qo])%N

/ -- per-path vectors at the solved params -> probabilities, VaR/ES, P&L stats
aB:$[W;aL qo;0];mv:$[W;aB 0;0];ag:$[W;aB 1;0];av2:$[W;aB 2;0];cv2:$[W;cV[qo;mv];0];pu2:$[W;pV[qo;ag];0];bv2:$[W;bV[mv;ag];0];pn:$[W;bv2+cv2+av2-pu2;0];bw2:$[W;$[on~"Yes";(kR qo`ki)&mx<ol;kR qo`ki];0];pt:{[x;p]h:(p%C)*-1+#x;i:`i$_h;$[i<-1+#x;x[i]+(h-i)*x[i+1]-x[i];x@i]};pa:$[W;(+/`f$ag)%n;0n]
lg:$[W;(+/mv%Y)%n;0n];pk:$[W;(+/`f$bw2)%n;0n];pl2:$[W;$[ye;(+/`f$bw2&T<qo`putk)%n;(+/`f$(~ag)&bw2)%n];0n];et:$[W;(+/T)%n;0n];sT:$[W;T@<T;0];t5:$[W;pt[sT;5];0n];t0:$[W;pt[sT;50];0n];t9:$[W;pt[sT;95];0n];lp:$[W;C*(N-pn)%N;0];sl2:$[W;lp@<lp;0];pmt:$[W;(+/`f$~ag)%n;0n]
v5:$[W;pt[sl2;95];0n];v9:$[W;pt[sl2;99];0n];e5:$[W;(+/sl2@&~sl2<v5)%1|+/~sl2<v5;0n];e9:$[W;(+/sl2@&~sl2<v9)%1|+/~sl2<v9;0n];pS:$[W;(+/pn<N)%n;0n];pG:$[W;(+/pn>N)%n;0n];mL:$[W;|/lp;0n];xr:$[W;(C*(+/pn)%N*n)-C;0n]
bP:$[W;C*(+/bv2)%N*n;0n];cP:$[W;C*(+/cv2)%N*n;0n];aP:$[W;C*(+/av2)%N*n;0n];uP:$[W;C*(+/pu2)%N*n;0n];hb:40;hl:$[W;&/T;0n];hh:$[W;|/T;0n];bn:$[W;(hb-1)&0|`i$_((T-hl)%1e-9|hh-hl)*hb;0];hi2:$[W;{+/bn=x}'!hb;0]

/ -- terminal histogram, per-date autocall counts, CRN bump helpers uS/uV/uR
/    (bumps re-derive q where engine.py does; all reuse the cached normals Z0)
dc:$[W;{`i$+/ag&mv=x}'ob;0];nm2:$[W;`i$+/~ag;0];uS:{[m]qP::SP*m;SS[SP*m;vo;qf'!nU];pf2[]};uV:{[dv]SS[SP;vo+dv;qy];pf2[]};uR:{[dr]R::r0+dr;qP::SP;SS[SP;vo;qf'!nU];pf2[]};r0:R;oh:{[i;b]@[nU#1.0;i;:;b]};du:$[g2;uS[nU#1.01];0n];dn:$[g2;uS[nU#0.99];0n]
dA:$[g2;(du-dn)%2.0;0n];gu:$[g2;uS[nU#1.05];0n];gd:$[g2;uS[nU#0.95];0n];gA:$[g2;((gu+gd)-2.0*pv2)%25.0;0n];vu:$[g2;uV[0.01];0n];vn:$[g2;uV[-0.01];0n];vA:$[g2;(vu-vn)%2.0;0n];ru:$[g2;uR[0.001];0n];rn:$[g2;uR[-0.001];0n];R:r0;rh:$[g2;(ru-rn)%20.0;0n]
dv2:$[dl;{[i]((uS oh[i;1.01])-uS oh[i;0.99])%2.0}'!nU;0n];vv2:$[dl;{[i]((uV @[nU#0.0;i;:;0.01])-uV @[nU#0.0;i;:;-0.01])%2.0}'!nU;0n]

/ restore base paths after the greek bumps
qP:sp;SS[sp;vo+vd;qy]

/ -- assemble output dicts (key names are the API contract) and emit JSON
gr:(`$("delta";"gamma";"vega";"rho";"delta_per_asset";"vega_per_asset"))!(dA;gA;vA;rh;dv2;vv2);lS:(`$("bond";"coupon";"autocall_coupon";"put"))!(bP;cP;aP;uP)
r1:(`$("p_autocall";"expected_life_y";"p_knock_in";"p_capital_loss";"exp_term_worst";"term_p05";"term_p50";"term_p95"))!(pa;lg;pk;pl2;et;t5;t0;t9)
r2b:(`$("var95_pct";"var99_pct";"es95_pct";"es99_pct";"p_loss";"p_gain";"max_loss_pct";"exp_return_pct";"p_maturity"))!(v5;v9;e5;e9;pS;pG;mL;xr;pmt);rk2:r1,r2b;ds:(`$("lo";"hi";"bins";"counts"))!(hl;hh;hb;hi2);ad2:(`$("days";"counts";"maturity_count"))!(ob;dc;nm2)
ou:`PV`Solved`solvable`legs`greeks`risk`dist`acdist!(rs`PV;rs`Solved;sb;lS;gr;rk2;ds;ad2)
`j@$[W;ou;rs,(,`solvable)!,sb]

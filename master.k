/ master.k - ngn/k autocallable / reverse-convertible pricer (golfed build)
/ Names are 1-2 chars; the long-name twin is master_readable.k (same output,
/ byte-for-byte - see golf_report.md). Reads json.json, prints one JSON blob.
/ Quick legend: C=100.0  Y=365.0  E=days  N=notional  R=rate  n=paths
/               T=terminal basket levels  Rf=basket path matrix  W=risk flag

/ -- config: J=payload, G pulls a string key, F is the empty-safe float cast
C:100.0;Y:365.0;J:`j?1:"json.json";mgOn:|/`margin=!J;mgSkip:$[mgOn;|/`gcache=!J@`margin;0b];pj:J@`platform;tj:J@`data;cj:J@`$"coupon_config";AC:J@`Autocall;aj:J@`$"Autocall_Coupon";G:{[d;k]d@`$k};F:{$[(@x)~`C;$[0=#x;0.0;`f$. x];`f$x]};so:G[pj;"Solve for"];rf2:F G[pj;"Reoffer (%)"]
mg:F pj@`$"Issuer Margin (%)";un:G[tj;"Underlying"];SP:`f$G[tj;"Spot Price"];nU:#un;w:G[tj;"Basket Type"];N:`f$G[tj;"Notional"];E:`i$G[tj;"Days"];dt:1.0%Y;sd:%dt;vo:`f$G[tj;"Volatility"];be:`f$G[tj;"Skew Beta"]
R:`f$G[tj;"Risk-Free Rate"];ba:G[tj;"Barrier Type"];k0:F G[tj;"KI Barrier (%)"];p0:F G[tj;"Put Strike (%)"];le:G[tj;"Leverage (%)"];on:G[tj;"One Star"];ol:F G[tj;"One Star Level (%)"];cg:G[tj;"Capital Guaranteed"];dj:G[tj;"Dividends"]
gv:$[^gg:J@`$"Capital Guarantee Level (%)";C;F gg];n:`i$J@`$"n_sims";sm:$[|/(`$"spot_mult")=!J;(nU#1.0)*`f$J@`$"spot_mult";nU#1.0];vd:$[|/(`$"vol_add")=!J;`f$J@`$"vol_add";0.0];rd2:$[|/(`$"rf_add")=!J;`f$J@`$"rf_add";0.0];R:R+rd2;sp:SP*sm

/ -- product-mode flags + dividend tables (per-underlying index/amount/day)
ia2:(ba~"American Daily Close")|ba~"American Intraday";ip:ia2|~(AC@`Type)~"None";at:aj@`$"Autocall Coupon Type";ac2:~at~"None";di:`i${x@`$"underlying_idx"}'dj;dm:`f${x@`amount}'dj

/ -- qf: dividend pv -> flat yield; qm..qn: shared Lehmer LCG + Box-Muller
/    (bit-identical to engine.py's _QSRng, so both engines draw the same paths)
dy:`f${x@`$"days_to_pay"}'dj;qf:{[i]pv:+/(di=i)*dm*`exp[-R*dy%Y];$[pv>0;(-`ln 1.0-pv%qP[i])%(E%Y);0.0]};qm:2147483647;qb:65536;qp:1_qb{qm!x*48271}\1;qt:42;qk:{[k]b:qm!qt*k#qp;qt::*|b;b};qz:{[m]f:`i$_m%qb;r:m-f*qb;(f#qb),$[r>0;,r;!0]}
qu:{[m](`f$,/qk'qz m)%qm};qn:{[m]u1:qu m;u2:qu m;(%-2.0*`ln u1)*`cos[6.283185307179586*u2]};hZ:(@J@`$"_Z")~`A;Z0:$[mgSkip;0;$[hZ;{(#x;#*x)#,/`f$'x}'J@`$"_Z";{(n;E)#qn n*E}'!nU]]

/ -- simulation: st2 = one local-vol step, sP path-dependent / sE European;
/    SS regenerates globals A0/M0/Rf/T/rm/mx for a given spot/vol/q set
st2:{[s;zt]cv:0.05|1.20&vB-b0*s;s*`exp[((rq-0.5*cv*cv)*dt)+cv*zt*sd]};sP:{[i]+(,(n#S0)),(n#S0)st2\+Z0[i]};sE:{[i]ex:((rq-0.5*V*V)*dt)+V*(%dt)*Z0[i];cs:+\'ex;S0,'S0*`exp cs}
sA:{[i]V::gV[i];B::be[i];S0::gS[i];Q::gQ[i];vB::V+B;b0::B%SP[i];rq::R-Q;$[ip;sP i;sE i]};mA:{[sv;vv;qv]gS::sv;gV::vv;gQ::qv;sA'!nU};nk:{(A0[x]%SP[x])*C}
SS:{[sv;vv;qv]A0::mA[sv;vv;qv];M0::nk'!nU;Rf::$[(nU=1)|w~"None";M0 0;w~"Worst-Of";&/M0;(+/M0)%nU];T::Rf[;E];rm::&/'Rf;mx::|/{M0[x][;E]}'!nU}

/ base paths (spot_mult / vol_add overrides applied here)
qP:sp;qy:qf'!nU;dz:$[mgSkip;0;SS[sp;vo+vd;qy]]

/ -- schedules: br2 = banker's rounding, ob = autocall observation days
fq:{$[x~"Monthly";12;x~"Quarterly";4;x~"SemiAnnually";2;x~"Yearly";1;1]};br2:{f:`i$_x;d:x-f;$[d<0.5;f;d>0.5;f+1;0=2!f;f;f+1]};cf:fq cj@`$"Coupon Frequency";im:(cj@`$"Coupon Frequency")~"At Maturity";ct:cj@`$"Coupon Type"
bD:`M`Q`S`Y!30 90 180 365;af:G[AC;"Autocallable From"];fd:(*bD@`$1#af)*(-1+`i$. 1_af);ax:fq AC@`$"Autocall Frequency";Em:E;mkSch:{[md]np2::$[im;1;`i$br2 (md%Y)*cf];au2::`i$br2 (md%Y)*ax;oa::br2'((1.0+!au2)%au2)*md;ob::$[au2<1;!0;oa@&~oa<fd];oi::!#ob;op::+(oi;ob)};mkSch E

/ -- autocall leg: aL folds as2 over (index;day) pairs op -> (mt;called;cpn)
bf:{[i]$[ay~"Variable Barrier";(*ab)+i*sv2;ay~"Custom Barrier";ab[i];*ab]};cf2:{[i]$[a2~"Snowball";(ap%ax)*(i+1)*N;a2~"Flat";ap*N;0.0]}
as2:{[st;ij]i:ij 0;d2:ij 1;cl:(~st 1)&~Rf[;d2]<bf i;((cl*d2)+(~cl)*st 0;(st 1)|cl;(st 2)+cl*(cf2 i)*`exp[-R*d2%Y])};ae:{[P]ay::AC@`Type;sv2::F G[AC;"Step Up / Down (%)"];ab::P`acb;ap::(P`acc)%C;a2::at}
aL:{[P]s0:(n#`f$Em;n#0b;n#0.0);$[(AC@`Type)~"None";s0;[ae P;$[(ay~"Issuer Callable")|0=#ob;s0;s0 as2/ op]]]};AB:{$[w~"Equally Weighted";~((+/{(A0[x][;cx]%SP[x])*C}'!nU)%nU)<cb2;&/{~A0[x][;cx]<SP[x]*cb2%C}'!nU]}

/ -- periodic coupon leg: cs2/cw2 fold pays into st; cm=at-maturity,
/    cu=fixed unconditional, cd=conditional(+memory); cV picks the branch
cs2:{[st;i]m2:(st 1)+pc;y2:(AB[])&$[ye;1b;~D>MT];((st 0)+(y2*m2)*`exp[-R*D%Y];$[ct~"Conditional with Memory";(~y2)*m2;ct~"Conditional without Memory";n#0.0;m2])};cw2:{[st;i]D::`i$_$[ye;(i%cf)*Y;(i%np2)*Em];cx::Em&D;cs2[st;i]};cm:{[c](MT=Em)*((c%C)*(Em%Y)*N)*`exp[-R*Em%Y]};fo:{[d](~d>MT)*pc*`exp[-R*d%Y]}
cu:{[c]pc::((c%C)%cf)*N;$[ye;n#pc*+/`exp[-R*(1.0+!np2)%cf];[fu::`i$_((1.0+!np2)%np2)*Em;$[np2<1;n#0.0;+/fo'fu]]]};cd:{[c;cb]pc::$[im;((c%C)*Em%Y)*N;((c%C)%cf)*N];cb2::cb;*(n#0.0;n#0.0)cw2/(1+!np2)}
cV:{[P;mt]MT::mt;c:P`c;$[ct~"None";n#0.0;im&ct~"Fixed Unconditional";cm c;ct~"Fixed Unconditional";cu c;cd[c;P`cb]]};cL:{[P;mt](+/cV[P;mt])%n};bg:$[ba~"American Intraday";`exp[0.5826*(*vo)*%dt];1.0];bR:{[ki]k2:ki*bg;$[ba~"European (Maturity)";~T>k2;ba~"None";n#1b;~rm>k2]};ye:(AC@`Type)~"None";kR:{[ki]k2:ki*bg;$[ye;$[ba~"None";T<qo`putk;(ba~"American Daily Close")|ba~"American Intraday";~rm>k2;~T>k2];$[(ba~"European (Maturity)")|ba~"None";T<k2;rm<k2]]}

/ -- put leg pV: barrier test bR, leverage lf, one-star & called exclusions
lf:{[u3]$[le~"Yes";C%u3;le~"No";1.0;(F le)%C]};pV:{[P;ia]$[cg~"Yes";n#0.0;[ki:P`ki;u3:P`putk;br:bR ki;br:$[on~"Yes";br&mx<ol;br];br:br&~ia;w2:0.0|u3-T;(br*w2*N%C)*(lf u3)*`exp[-R*Em%Y]]]};pL:{[P;ia](+/pV[P;ia])%n}

/ -- bond redemption bV (capital-guarantee cap) and total price pp
bV:{[mt;ia]N*`exp[-R*mt%Y]};pp:{[P]a:aL[P];mt:a 0;ia:a 1;a3:(+/a 2)%n;o2:(+/bV[mt;ia])%n;o2+(cL[P;mt])+a3-pL[P;ia]};b2:F G[AC;"Autocall Barrier (%)"]

/ -- parameter dict pb; pw reprices with one key swapped; sk = solve target
pb:`c`cb`ki`putk`acb`acc!(F cj@`$"Coupon (%)";F cj@`$"Coupon Barrier Level (%)";k0;p0;b2;F aj@`$"AC Coupon (%)");pw:{[k;x]Q:pb;Q[k]:x;pp[Q]}
sk:$[so~"Coupon (%)";`c;so~"KI Barrier (%)";`ki;so~"Coupon Barrier Level (%)";`cb;so~"Put Strike (%)";`putk;so~"Autocall Coupon (%)";`acc;so~"Autocall Barrier (%)";`acb;`none]

/ -- solver: secant/bisection to tolerance tl; sb flips to 0 if no bracket
tl:1e-7;sb:1;bs2:{[l;h;fl;fh]d:fh-fl;sx:$[0.0=d;.5*l+h;h-fh*(h-l)%d];$[(sx>l)&sx<h;sx;0.5*l+h]};bp:{[o]l:o 0;h:o 1;fl:o 2;fh:o 3;$[(h-l)<tl;o;[sx:bs2[l;h;fl;fh];fs:(pw[sg;sx])-tg;$[(0.0<fs)~0.0<fl;(sx;h;fs;fh);(l;sx;fl;fs)]]]}
sw:{[k;t3;lo;hi]sg::k;tg::t3;fl:(pw[k;lo])-t3;fh:(pw[k;hi])-t3;$[(0.0<fl)~0.0<fh;[sb::0;$[(fl*fl)<fh*fh;lo;hi]];(bp/(lo;hi;fl;fh))0]};sR:{[]t3:N*(rf2-mg)%C;sv:sw[sk;t3;0.0001;200.0];q:pb;q[sk]:sv;`PV`Solved!(C*(pp[q])%N;sv)}

/ -- headline result rs; greeks flag gates: W legs+risk, g2 basket, dl per-asset
pR:{[]px:C*(pp[pb])%N;`PV`Solved!(px;px+mg)};rs:$[mgSkip;`PV`Solved!(0.0;0.0);$[so~"Reoffer (%)";pR[];sR[]]];gk2:$[mgSkip;0;$[mgOn;3;$[^gk:J@`greeks;0;`i$F gk]]];W:gk2>0;g2:gk2>1;dl:gk2>2;qo:pb;qo:$[sk~`none;qo;@[qo;sk;:;rs`Solved]];pf2:{[]C*(pp[qo])%N};pv2:$[mgSkip;0.0;C*(pp[qo])%N]

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
qP:sp;dz:$[mgSkip;0;SS[sp;vo+vd;qy]]

/ -- theta: 1-day time decay. CRN => Days-1 paths are the base paths truncated by
/    one column, so reprice on the restored base Rf/M0 at maturity Em-1 (no re-sim).
thP:{[md]z0T:T;z0r:rm;z0m:mx;z0E:Em;z0n:np2;z0a:au2;z0o:ob;z0i:oi;z0p:op;z0oa:oa;Em::md;mkSch md;T::Rf[;md];rm::&/'(md+1)#'Rf;mx::|/M0[;;md];px:C*(pp[qo])%N;Em::z0E;np2::z0n;au2::z0a;oa::z0oa;ob::z0o;oi::z0i;op::z0p;T::z0T;rm::z0r;mx::z0m;px};th:$[g2;(thP[E-1])-pv2;0n]

/ -- assemble output dicts (key names are the API contract) and emit JSON
gr:(`$("delta";"gamma";"vega";"rho";"theta";"delta_per_asset";"vega_per_asset"))!(dA;gA;vA;rh;th;dv2;vv2);lS:(`$("bond";"coupon";"autocall_coupon";"put"))!(bP;cP;aP;uP)
r1:(`$("p_autocall";"expected_life_y";"p_knock_in";"p_capital_loss";"exp_term_worst";"term_p05";"term_p50";"term_p95"))!(pa;lg;pk;pl2;et;t5;t0;t9)
r2b:(`$("var95_pct";"var99_pct";"es95_pct";"es99_pct";"p_loss";"p_gain";"max_loss_pct";"exp_return_pct";"p_maturity"))!(v5;v9;e5;e9;pS;pG;mL;xr;pmt);rk2:r1,r2b;ds:(`$("lo";"hi";"bins";"counts"))!(hl;hh;hb;hi2);ad2:(`$("days";"counts";"maturity_count"))!(ob;dc;nm2)
ou:`PV`Solved`solvable`legs`greeks`risk`dist`acdist!(rs`PV;rs`Solved;sb;lS;gr;rk2;ds;ad2)

/ ############################################################################
/ ##  MARGIN & COLLATERAL -- native Amber; mirrors engine.py compute_margin. ##
/ ##  Top-level statements accumulate every intermediate into ONE global dict ##
/ ##  S (respects the interpreter's per-lambda 16-local / 255-const caps and  ##
/ ##  the 256-global table). The MC only runs when a `margin` ticket is set.  ##
/ ############################################################################
mgP:$[mgOn;J@`margin;(,`zz)!,0.0];mgh:{[k;d]$[|/(`$k)=!mgP;mgP@`$k;d]};mgf:{[k;d]F mgh[k;d]};mgb:{[k;d]$[|/(`$k)=!mgP;0.0<`f$mgP@`$k;d]};abz:{x*1.0-2.0*x<0.0}
ppf:{[p]zA:-39.69683028665376 220.9460984245205 -275.9285104469687 138.3577518672690 -30.66479806614716 2.506628277459239;zB:-54.47609879822406 161.5858368580409 -155.6989798598866 66.80131188771972 -13.28068155288572 1.0;zC:-0.007784894002430293 -0.3223964580411365 -2.400758277161838 -2.549732539343734 4.374664141464968 2.938163982698783;zD:0.007784695709041462 0.3224671290700398 2.445134137142996 3.754408661907416 1.0;hr:{[co;x]{[x;a;c]c+x*a}[x]/[co]};$[~p>0.0;-1e18;~p<1.0;1e18;p<0.02425;[q:%(-2.0*`ln p);(hr[zC;q])%hr[zD;q]];~p>0.97575;[q:p-0.5;r:q*q;(q*hr[zA;r])%hr[zB;r]];[q:%(-2.0*`ln[1.0-p]);(-(hr[zC;q])%hr[zD;q])]]}
mPct:{[x;q]pt[x@<x;q]};wrst:{[x;cf](mPct[x;cf])|(-mPct[x;100.0-cf])};mkL:{[f;g;m;c;ch](`$("factor";"greek";"mult";"charge";"charged"))!(f;g;m;c;ch)};tmn:{[p;t;n]$[n>0;(-+/p@&t)%n;0.0]}
S:(,`mNot)!,$[(mgf["notional";0.0])>0.0;mgf["notional";0.0];N]
S:S,(,`gkc)!,mgh["gcache";()!()]
S:S,(,`usePer)!,nU>1
S:S,(,`netD)!,mgb["charge_abs_delta";1b]
S:S,(,`dAx)!,$[mgSkip;F (S`gkc)@`delta;dA]
S:S,(,`dv2x)!,$[mgSkip;$[nU>1;F'(S`gkc)@`$"per_asset";,S`dAx];dv2]
S:S,(,`gD)!,$[(S`usePer);$[(S`netD);+/S`dv2x;($[(+/S`dv2x)<0.0;-1.0;1.0])*+/abz S`dv2x];S`dAx]
S:S,(,`nFac)!,$[(S`usePer);nU;1]
S:S,(,`gG)!,$[mgSkip;F (S`gkc)@`gamma;gA]
S:S,(,`gV)!,$[mgSkip;F (S`gkc)@`vega;vA]
S:S,(,`gR)!,$[mgSkip;F (S`gkc)@`rho;rh]
S:S,(,`gT)!,$[mgSkip;F (S`gkc)@`theta;th]
S:S,(,`rvol)!,1e-6|mgf["risk_vol";vo 0]
S:S,(,`mpor)!,0.5|mgf["mpor_days";10.0]
S:S,(,`cfp)!,50.001|99.999&mgf["conf_pct";99.0]
S:S,(,`vov)!,0.0|mgf["vol_of_vol";0.9]
S:S,(,`rvb)!,0.0|mgf["rate_vol_bp";100.0]
S:S,(,`rhosv)!,-0.999|0.999&mgf["rho_spot_vol";0.0]
S:S,(,`sd0)!,`i$mgf["seed";0.0]
S:S,(,`nsm)!,$[mgOn;2000|`i$mgf["n_sims";100000.0];1]
S:S,(,`mh)!,(S`mpor)%252.0
S:S,(,`zq)!,ppf[(S`cfp)%100.0]
S:S,(,`ss)!,(S`rvol)*%S`mh
S:S,(,`sv)!,(S`vov)*%S`mh
S:S,(,`mDl)!,100.0*`exp[((S`zq)*S`ss)-0.5*(S`ss)*S`ss]-1.0
S:S,(,`mVg)!,(S`rvol)*100.0*`exp[((S`zq)*S`sv)-0.5*(S`sv)*S`sv]-1.0
S:S,(,`mGm)!,0.5*(S`mDl)*S`mDl
S:S,(,`mRh)!,(S`zq)*(S`rvb)*%S`mh
S:S,(,`MN)!,{qt::42+x;qn 3*y}[S`sd0;S`nsm]
S:S,(,`dsh)!,100.0*`exp[((S`ss)*(S`nsm)#S`MN)-0.5*(S`ss)*S`ss]-1.0
S:S,(,`dvh)!,(S`rvol)*100.0*`exp[((S`sv)*((S`rhosv)*(S`nsm)#S`MN)+(%(1.0-(S`rhosv)*S`rhosv))*(S`nsm)#(S`nsm)_S`MN)-0.5*(S`sv)*S`sv]-1.0
S:S,(,`drh)!,(S`rvb)*(%S`mh)*(S`nsm)#(2*S`nsm)_S`MN
S:S,(,`mDe)!,wrst[S`dsh;S`cfp]
S:S,(,`mVe)!,wrst[S`dvh;S`cfp]
S:S,(,`dropG)!,(mgb["ignore_pos_gamma";1b])&(S`gG)>0.0
S:S,(,`dropV)!,(mgb["ignore_pos_vega";1b])&(S`gV)>0.0
S:S,(,`igT)!,mgb["ignore_pos_theta";1b]
S:S,(,`measure)!,$[(mgh["measure";"var"])~"es";"es";"var"]
S:S,(,`schr)!,0.0|mgf["schedule_rate";8.0]
S:S,(,`thc)!,0.0|(-S`gT)*S`mpor
S:S,(,`sChD)!,(abz S`gD)*S`mDl
S:S,(,`sChG)!,$[(S`dropG);0.0;(-S`gG)*S`mGm]
S:S,(,`sChV)!,$[(S`dropV);0.0;(-S`gV)*S`mVg]
S:S,(,`sChR)!,(abz S`gR)*S`mRh
S:S,(,`sGross)!,(S`sChD)+(S`sChG)+(S`sChV)+(S`sChR)+S`thc
S:S,(,`m2im)!,0.0|S`sGross
S:S,(,`pnlD)!,(S`gD)*S`dsh
S:S,(,`pnlG)!,$[(S`dropG);(S`nsm)#0.0;(0.5*S`gG)*(S`dsh)*S`dsh]
S:S,(,`pnlV)!,$[(S`dropV);(S`nsm)#0.0;(S`gV)*S`dvh]
S:S,(,`pnlR)!,(S`gR)*S`drh
S:S,(,`carry)!,$[(S`igT)&((S`gT)*S`mpor)>0.0;0.0;(S`gT)*S`mpor]
S:S,(,`pnlM)!,((S`pnlD)+(S`pnlG)+(S`pnlV)+S`pnlR)+S`carry
S:S,(,`cutv)!,mPct[S`pnlM;100.0-S`cfp]
S:S,(,`tailm)!,~(S`pnlM)>S`cutv
S:S,(,`ntl)!,+/S`tailm
S:S,(,`varv)!,-S`cutv
S:S,(,`esv)!,$[(S`ntl)>0;(-+/(S`pnlM)@&S`tailm)%S`ntl;S`varv]
S:S,(,`m3im)!,0.0|$[(S`measure)~"es";S`esv;S`varv]
S:S,(,`atD)!,tmn[S`pnlD;S`tailm;S`ntl]
S:S,(,`atG)!,tmn[S`pnlG;S`tailm;S`ntl]
S:S,(,`atV)!,tmn[S`pnlV;S`tailm;S`ntl]
S:S,(,`atR)!,tmn[S`pnlR;S`tailm;S`ntl]
S:S,(,`atT)!,tmn[(S`nsm)#S`carry;S`tailm;S`ntl]
S:S,(,`var95v)!,-mPct[S`pnlM;5.0]
S:S,(,`var99v)!,-mPct[S`pnlM;1.0]
S:S,(,`hlo)!,mPct[S`pnlM;0.2]
S:S,(,`hhi)!,$[~(mPct[S`pnlM;99.8])>S`hlo;(S`hlo)+1.0;mPct[S`pnlM;99.8]]
S:S,(,`hbn)!,44
S:S,(,`hbix)!,((S`hbn)-1)&0|`i$_(((S`pnlM)-S`hlo)*S`hbn)%(S`hhi)-S`hlo
S:S,(,`hinr)!,(~(S`pnlM)<S`hlo)&~(S`pnlM)>S`hhi
S:S,(,`hcnt)!,{[b;m;x]+/(b=x)&m}[S`hbix;S`hinr]'!S`hbn
S:S,(,`sgP)!,`f$mgh["spot_grid_pct";-30.0 -20.0 -10.0 -5.0 0.0 5.0 10.0 20.0]
S:S,(,`vgP)!,`f$mgh["vol_grid_pts";-10.0 -5.0 0.0 5.0 10.0 20.0]
S:S,(,`pGrid)!,{[d;g;v;s;vv]((d*s)+(0.5*g*s*s))+v*vv}[S`gD;S`gG;S`gV;S`sgP]'S`vgP
S:S,(,`gFlat)!,,/S`pGrid
S:S,(,`wP)!,&/S`gFlat
S:S,(,`wIx)!,(S`gFlat)?S`wP
S:S,(,`wI)!,`i$_(S`wIx)%#S`sgP
S:S,(,`wJ)!,(S`wIx)-(S`wI)*#S`sgP
S:S,(,`cAll)!,mgh["collateral";()]
S:S,(,`ncol)!,#S`cAll
S:S,(,`cMv)!,$[(S`ncol)>0;`f$(S`cAll)@\:`market;0#0.0]
S:S,(,`cLtv)!,$[(S`ncol)>0;`f$(S`cAll)@\:`$"ltv_pct";0#0.0]
S:S,(,`cHc)!,$[(S`ncol)>0;`f$(S`cAll)@\:`$"haircut_pct";0#0.0]
S:S,(,`cEx)!,$[(S`ncol)>0;0.0<`f$(S`cAll)@\:`exempt;0#0b]
S:S,(,`cNm)!,$[(S`ncol)>0;(S`cAll)@\:`name;()]
S:S,(,`cCy)!,$[(S`ncol)>0;(S`cAll)@\:`ccy;()]
S:S,(,`cGr)!,$[(S`ncol)>0;(S`cAll)@\:`group;()]
S:S,(,`cAl)!,(S`cMv)*(S`cLtv)%100.0
S:S,(,`cGex)!,$[(S`ncol)>0;{[a;e]+/a*e}[S`cAl]'(`$'S`cGr)=\:`$'S`cGr;0#0.0]
S:S,(,`totMv)!,+/S`cMv
S:S,(,`capv)!,(S`totMv)*(0.0|mgf["conc_pct";25.0])%100.0
S:S,(,`xhc)!,(0.0|100.0&mgf["excess_haircut_pct";30.0])%100.0
S:S,(,`cFac)!,$[(S`ncol)>0;{[gx;a;ex;cp;xh;i]$[(ex i)|(~gx[i]>cp)|(~a[i]>0.0)|~cp>0.0;1.0;(cp+(gx[i]-cp)*1.0-xh)%gx[i]]}[S`cGex;S`cAl;S`cEx;S`capv;S`xhc]'!S`ncol;0#0.0]
S:S,(,`cAc)!,(S`cAl)*S`cFac
S:S,(,`cHr)!,(S`cAc)*(S`cHc)%100.0
S:S,(,`cEl)!,(S`cAc)-S`cHr
S:S,(,`mLine)!,+/S`cEl
S:S,(,`cRows)!,{[m;i](`$("name";"ccy";"group";"exempt";"market";"after_ltv";"factor";"after_conc";"haircut";"eligible"))!m@\:i}[(S`cNm;S`cCy;S`cGr;S`cEx;S`cMv;S`cAl;S`cFac;S`cAc;S`cHr;S`cEl)]'!S`ncol
S:S,(,`mth0)!,mgh["method";"2"]
S:S,(,`msym)!,`$S`mth0
S:S,(,`mth)!,$[((S`msym)~`$"1")|((S`msym)~`$"2")|(S`msym)~`$"3";$S`msym;"2"]
S:S,(,`grSel)!,$[(S`msym)~`$"1";S`schr;(S`msym)~`$"3";S`m3im;S`m2im]
S:S,(,`gMiss)!,(~(S`msym)~`$"1")&1e-12>(abz S`gD)|(abz S`gG)|(abz S`gV)|(abz S`gR)|abz S`gT
S:S,(,`grB)!,$[(S`gMiss);S`schr;S`grSel]
S:S,(,`useFl)!,mgb["use_schedule_floor";0b]
S:S,(,`flPct)!,$[(S`useFl)&~(S`msym)~`$"1";S`schr;0.0]
S:S,(,`grF)!,$[(S`useFl)&~(S`msym)~`$"1";(S`grB)|S`schr;S`grB]
S:S,(,`mtmP)!,mgf["mtm_pct";0.0]
S:S,(,`vmP)!,$[(S`mtmP)<0.0;-S`mtmP;0.0]
S:S,(,`mtCr)!,$[mgb["use_mtm";0b];0.0|S`mtmP;0.0]
S:S,(,`imV)!,(0.0|S`grF)+S`vmP
S:S,(,`mmV)!,(S`imV)*mgf["mm_mult";0.9]
S:S,(,`cmV)!,(S`imV)*mgf["cm_mult";0.8]
S:S,(,`linePct)!,(((S`mLine)%S`mNot)*100.0)+S`mtCr
S:S,(,`statusV)!,$[(S`linePct)<S`cmV;"liquidate";(S`linePct)<S`mmV;"margin_call";(S`linePct)<S`imV;"below_im";"hold"]
S:S,(,`covV)!,$[(S`imV)>1e-9;((S`linePct)%S`imV)*100.0;0n]
S:S,(,`tayE)!,$[(S`m3im)>1e-9;(((S`m2im)-S`m3im)%S`m3im)*100.0;0.0]
sLines:(mkL["delta";S`gD;S`mDl;S`sChD;1];mkL["gamma";S`gG;S`mGm;S`sChG;~S`dropG];mkL["vega";S`gV;S`mVg;S`sChV;~S`dropV];mkL["rho";S`gR;S`mRh;S`sChR;1];mkL["theta";S`gT;S`mpor;S`thc;(S`thc)>0.0])
dropD:(`$("gamma";"vega"))!((S`dropG);S`dropV)
attrD:(`$("delta";"gamma";"vega";"rho";"theta"))!(S`atD;S`atG;S`atV;S`atR;S`atT)
histD:(`$("lo";"hi";"bins";"counts";"cut"))!(S`hlo;S`hhi;S`hbn;S`hcnt;S`cutv)
mgMul:(`$("z";"m_delta";"m_gamma";"m_vega";"m_rho";"m_delta_empirical";"m_vega_empirical";"sd_spot";"sd_vol";"risk_vol";"vol_of_vol";"rate_vol_bp";"rho_spot_vol";"mpor_days";"conf_pct";"n_sims";"seed"))!(S`zq;S`mDl;S`mGm;S`mVg;S`mRh;S`mDe;S`mVe;S`ss;S`sv;S`rvol;S`vov;S`rvb;S`rhosv;S`mpor;S`cfp;S`nsm;S`sd0)
mgGk:(`$("delta";"gamma";"vega";"rho";"theta";"per_asset";"n_factors"))!(S`gD;S`gG;S`gV;S`gR;S`gT;$[(S`usePer);S`dv2x;0n];S`nFac)
sLnS:,(`$("factor";"greek";"mult";"charge";"charged"))!("notional";100.0;(S`schr)%100.0;S`schr;1)
mSch:(`$("im_pct";"im_amount";"lines"))!(S`schr;((S`schr)%100.0)*S`mNot;sLnS)
mSen:(`$("im_pct";"gross_pct";"lines";"dropped"))!(S`m2im;S`sGross;sLines;dropD)
mVar:(`$("im_pct";"var_pct";"es_pct";"var95";"var99";"measure";"attribution";"attribution_total";"dropped";"tail_scenarios";"hist"))!(S`m3im;S`varv;S`esv;S`var95v;S`var99v;S`measure;attrD;(S`atD)+(S`atG)+(S`atV)+(S`atR)+S`atT;dropD;S`ntl;histD)
metD:(`$("schedule";"greeks";"var"))!(mSch;mSen;mVar)
wSc:(`$("vol_shock_pts";"spot_shock_pct"))!((S`vgP)S`wI;(S`sgP)S`wJ)
sgD:(`$("spot_shocks_pct";"vol_shocks_pts";"pnl_grid";"worst_pnl_pct";"worst_scenario";"worst_pnl_amount"))!(S`sgP;S`vgP;S`pGrid;S`wP;wSc;((S`wP)%100.0)*S`mNot)
collD:(`$("rows";"total_market";"cap";"margin_line";"conc_pct";"excess_haircut_pct"))!(S`cRows;S`totMv;S`capv;S`mLine;mgf["conc_pct";25.0];mgf["excess_haircut_pct";30.0])
mgR:$[mgOn;(`$("method";"multipliers";"greeks";"underlyings";"net_delta";"methods";"attribution";"stress_grid";"gross_pct";"schedule_floor_pct";"greeks_missing";"mtm_pct";"mtm_credit_pct";"variation_margin_pct";"variation_margin_amount";"im_pct";"im_amount";"maintenance_margin_pct";"maintenance_margin_amount";"closeout_margin_pct";"closeout_margin_amount";"collateral";"margin_line_pct";"margin_line_amount";"coverage_pct";"taylor_error_pct";"status";"notional"))!(S`mth;mgMul;mgGk;un;S`netD;metD;attrD;sgD;S`grF;S`flPct;S`gMiss;S`mtmP;S`mtCr;S`vmP;((S`vmP)%100.0)*S`mNot;S`imV;((S`imV)%100.0)*S`mNot;S`mmV;((S`mmV)%100.0)*S`mNot;S`cmV;((S`cmV)%100.0)*S`mNot;collD;S`linePct;((S`linePct)%100.0)*S`mNot;S`covV;S`tayE;S`statusV;S`mNot);0]
`j@$[mgOn;mgR;$[W;ou;rs,(,`solvable)!,sb]]

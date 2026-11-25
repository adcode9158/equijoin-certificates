// Single-threaded decision over filtered bag equijoins. Inputs are typed resident columns.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using namespace std;
using Value=int64_t;
using Mass=unsigned __int128;
using Clock=chrono::steady_clock;
constexpr Value Null=numeric_limits<Value>::min();
uint64_t Budget=10000000;
struct Term {int column, op; Value literal;};
struct Input {int table, key; vector<Term> terms;};
struct Query {string id; bool full; uint64_t truth; vector<int> input;};
struct Table {vector<vector<Value>> cols; int n;};
struct Store {
    vector<Table> tables;
    vector<Input> inputs;
    vector<Query> queries;
    Store(const string& dir) {
        ifstream meta(dir+"/catalog.txt"), binary(dir+"/columns.bin",ios::binary);
        meta.exceptions(ios::badbit | ios::failbit); binary.exceptions(ios::badbit | ios::failbit);
        int n; meta>>n;
        tables.resize(n);
        for(auto &t:tables) {
            int cols; meta>>cols>>t.n; t.cols.resize(cols);
            for(auto &c:t.cols) {c.resize(t.n); binary.read(reinterpret_cast<char*>(c.data()),8*t.n);}
        }
        meta>>n; inputs.resize(n);
        for(auto &i:inputs) {
            int k; meta>>i.table>>i.key>>k; i.terms.resize(k);
            for(auto &p:i.terms) meta>>p.column>>p.op>>p.literal;
        }
        meta>>n; queries.resize(n);
        for(auto &q:queries) {
            int k; meta>>q.id>>q.full>>q.truth>>k; q.input.resize(k);
            Mass product_bound=1;
            for(int &id:q.input) {
                meta>>id;
                const unsigned rows=tables.at(inputs.at(id).table).n;
                if(rows && product_bound>(~Mass(0))/rows) throw runtime_error("128-bit bound exceeded");
                product_bound*=rows;
            }
        }
    }
    bool match(const Input &i,int row) const {
        for(const auto &p:i.terms) {
            Value v=tables[i.table].cols[p.column][row];
            if(v==Null || (p.op==0 && v!=p.literal) || (p.op>0 && v<p.literal) ||
               (p.op<0 && v>p.literal)) return false;
        }
        return true;
    }
};
int slot(Value key) {
    if(key < -1 || key > 1000000) throw runtime_error("key beyond fixture's dense integer range");
    return static_cast<int>(key)+1;
}
struct Groups {
    vector<int> offset, rows, keys;
    Groups(const vector<Value>& column, bool need_rows) {
        int last=0;
        for(Value v:column) if(v!=Null) last=max(last,slot(v));
        offset.assign(last+2,0);
        for(Value v:column) if(v!=Null) ++offset[slot(v)+1];
        for(int k=0;k<=last;++k) {
            if(offset[k+1]) keys.push_back(k);
            offset[k+1]+=offset[k];
        }
        if(!need_rows) return;
        auto cursor=offset; rows.resize(offset.back());
        for(size_t r=0;r<column.size();++r) if(column[r]!=Null) rows[cursor[slot(column[r])]++]=r;
    }
    int count(int k) const {return size_t(k+1)<offset.size()?offset[k+1]-offset[k]:0;}
};
struct Counts {vector<int> freq, keys;};
struct Head {Mass total=0; vector<pair<Mass,int>> keys; vector<int> ids;};
enum class Policy {Group, Memo, KeyScan, Zero, Reject, Bound, Resume, Natural};
struct Run {
    const Store &s;
    Policy policy;
    map<pair<int,int>,Groups> postings;
    map<vector<pair<int,int>>,Head> heads;
    map<int,Counts> cache;
    int opened=0, fallback=0, builds=0;
    Run(const Store &source, Policy p):s(source),policy(p){}
    const Groups &groups(const Input &i) {
        const auto k=make_pair(i.table,i.key);
        auto found=postings.find(k);
        if(found!=postings.end()) return found->second;
        return postings.try_emplace(k,s.tables[i.table].cols[i.key],policy!=Policy::Zero).first->second;
    }
    Counts filtered(int id) const {
        const auto &i=s.inputs[id]; const auto &t=s.tables[i.table];
        Counts out; const auto &col=t.cols[i.key];
        for(int r=0;r<t.n;++r) if(col[r]!=Null && s.match(i,r)) {
            int k=slot(col[r]);
            if(size_t(k)>=out.freq.size()) out.freq.resize(k+1,0);
            if(!out.freq[k]++) out.keys.push_back(k);
        }
        return out;
    }
    bool aggregate(const Query &q) {
        vector<Counts> scratch; scratch.reserve(q.input.size());
        vector<const Counts*> all;
        for(int id:q.input) {
            if(policy==Policy::Group) {
                scratch.push_back(filtered(id)); all.push_back(&scratch.back());
            } else {
                auto iter=cache.find(id);
                if(iter==cache.end()) iter=cache.emplace(id,filtered(id)).first;
                all.push_back(&iter->second);
            }
        }
        sort(all.begin(),all.end(),[](auto a,auto b){return a->keys.size()<b->keys.size();});
        Mass exact=0;
        for(int k:all.front()->keys) {
            Mass w=1;
            for(auto a:all) {
                if(size_t(k)>=a->freq.size() || !a->freq[k]) {w=0;break;}
                w*=a->freq[k];
            }
            exact+=w;
            if(policy!=Policy::Group && exact>Budget) return false;
        }
        if(exact!=q.truth) throw runtime_error("aggregate mismatch: "+q.id);
        return exact<=Budget;
    }
    static Head build(const vector<const Groups*> &list,bool need_head) {
        Head head;
        auto drive=*min_element(list.begin(),list.end(),[](auto a,auto b){return a->keys.size()<b->keys.size();});
        vector<pair<Mass,int>> weights;
        for(int k:drive->keys) {
            Mass w=1;
            for(auto g:list) {w*=g->count(k);if(!w) break;}
            if(w) {head.total+=w; if(need_head) weights.emplace_back(w,k);}
        }
        size_t len=min<size_t>(64,weights.size());
        partial_sort(weights.begin(),weights.begin()+len,weights.end(),greater<pair<Mass,int>>());
        head.keys.assign(weights.begin(),weights.begin()+len);
        for(auto term:head.keys) head.ids.push_back(term.second);
        sort(head.ids.begin(),head.ids.end());
        return head;
    }
    Mass value(const Query& q,const vector<const Groups*> &list,int k) const {
        array<pair<int,int>,16> order;
        if(list.size()>order.size()) throw runtime_error("arity outside fixture");
        for(size_t j=0;j<list.size();++j) order[j]={list[j]->count(k),int(j)};
        sort(order.begin(),order.begin()+list.size());
        Mass value=1;
        for(size_t h=0;h<list.size();++h) {
            auto [n,j]=order[h]; const auto &in=s.inputs[q.input[j]];
            if(!in.terms.empty()) {
                int hits=0; const auto &group=*list[j];
                for(int pos=group.offset[k];pos<group.offset[k+1];++pos)
                    hits+=s.match(in,group.rows[pos]);
                n=hits;
            }
            if(!n) return 0;
            value*=n;
        }
        return value;
    }
    bool decide(const Query &q) {
        opened=fallback=builds=0;
        if(policy==Policy::Group || policy==Policy::Memo) return aggregate(q);
        vector<const Groups*> list; vector<pair<int,int>> shape;
        for(int id:q.input) {
            const auto &i=s.inputs[id]; list.push_back(&groups(i)); shape.emplace_back(i.table,i.key);
        }
        if(policy==Policy::KeyScan) {
            auto drive=*min_element(list.begin(),list.end(),[](auto a,auto b){return a->keys.size()<b->keys.size();});
            Mass total=0;
            for(int k:drive->keys) {
                bool common=all_of(list.begin(),list.end(),[k](auto g){return g->count(k)>0;});
                if(common) total+=value(q,list,k);
                if(total>Budget) return false;
            }
            if(total!=q.truth) throw runtime_error("key-at-a-time count mismatch");
            return true;
        }
        sort(shape.begin(),shape.end());
        auto found=heads.find(shape);
        if(found==heads.end()) {found=heads.emplace(shape,build(list,policy!=Policy::Zero && policy!=Policy::Natural)).first; ++builds;}
        const Head &head=found->second;
        Mass lo=0, tail=head.total;
        if(policy!=Policy::Reject && tail<=Budget) return true;
        if(policy!=Policy::Zero && policy!=Policy::Natural) for(auto [w,k]:head.keys) {
            auto exact=value(q,list,k); ++opened;
            if(exact>w) throw runtime_error("key cap broken");
            lo+=exact; tail-=w;
            if(lo>Budget) return false;
            if((policy==Policy::Bound || policy==Policy::Resume) && lo+tail<=Budget) return true;
        }
        ++fallback;
        if(policy==Policy::Resume || policy==Policy::Natural) {
            auto drive=*min_element(list.begin(),list.end(),[](auto a,auto b){return a->keys.size()<b->keys.size();});
            for(int k:drive->keys) {
                if(binary_search(head.ids.begin(),head.ids.end(),k)) continue;
                Mass cap=1;
                for(auto g:list) {cap*=g->count(k); if(!cap) break;}
                if(!cap) continue;
                lo+=value(q,list,k); tail-=cap;
                if(lo>Budget) return false;
                if(lo+tail<=Budget) return true;
            }
            throw runtime_error("nonempty interval after completing scan");
        }
        return aggregate(q);
    }
};
int main(int argc,char **argv) {
    if(argc!=4 && argc!=5) {cerr<<"Usage: bench FIXTURE OUTPUT REPETITIONS [BUDGET]\n"; return 2;}
    if(argc==5) Budget=stoull(argv[4]);
    Store store(argv[1]); ofstream out(argv[2]); out.exceptions(ios::badbit|ios::failbit);
    vector<Policy> policies={Policy::Memo,Policy::Bound,Policy::Group,Policy::Zero,Policy::Reject,Policy::KeyScan,Policy::Resume,Policy::Natural};
    map<Policy,string> names={{Policy::Group,"scan_exact"},{Policy::Memo,"memo_capped"},{Policy::Resume,"head_resume"},{Policy::Natural,"natural_resume"},{Policy::KeyScan,"indexed_keys"},{Policy::Zero,"base_only"},
        {Policy::Reject,"head_reject"},{Policy::Bound,"head_both"}};
    out<<"cohort,round,policy,case_id,truth,ns,keys_opened,fallback,shape_build\n";
    for(string cohort:{"full","subplan"}) for(int r=0;r<stoi(argv[3]);++r) {
        for(size_t j=0;j<policies.size();++j) {
            auto p=policies[(j+r)%policies.size()]; Run run(store,p);
            for(const Query &q:store.queries) {
                if(q.full!=(cohort=="full")) continue;
                auto start=Clock::now(); bool fit=run.decide(q);
                auto ns=chrono::duration_cast<chrono::nanoseconds>(Clock::now()-start).count();
                if(fit!=(q.truth<=Budget)) throw runtime_error("decision mismatch: "+q.id);
                out<<cohort<<','<<r<<','<<names[p]<<','<<q.id<<','<<q.truth<<','<<ns<<','
                   <<run.opened<<','<<run.fallback<<','<<run.builds<<'\n';
            }
        }
        out.flush(); cerr<<cohort<<" round "<<r+1<<"\n";
    }
}




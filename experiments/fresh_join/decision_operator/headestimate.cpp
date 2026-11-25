// Approximate the output rows from the same resident inputs available to the exact certificate.
#define main archived_benchmark_entry
#include "../multiway_joins/bench.cpp"
#undef main
#include <iomanip>

int main(int argc,char** argv) {
    if(argc!=4) return 2;
    Store store(argv[1]);
    Run run(store,Policy::Resume);
    map<string,const Query*> queries;
    for(const auto& query:store.queries) queries.emplace(query.id,&query);
    ifstream schedule(argv[2]); ofstream result(argv[3]);
    result<<"case,head_lower,head_ratio,unfiltered\n"<<setprecision(21);
    string id;
    while(schedule>>id) {
        const auto& q=*queries.at(id);
        vector<const Groups*> list;
        vector<pair<int,int>> shape;
        for(int input_id:q.input) {
            const auto& input=store.inputs.at(input_id);
            list.push_back(&run.groups(input));
            shape.emplace_back(input.table,input.key);
        }
        sort(shape.begin(),shape.end());
        auto it=run.heads.find(shape);
        if(it==run.heads.end()) it=run.heads.emplace(shape,Run::build(list,true)).first;
        const Head& head=it->second;
        Mass opened=0,filtered=0;
        for(const auto& term:head.keys) {
            opened+=term.first;
            filtered+=run.value(q,list,term.second);
        }
        long double ratio=opened ? (long double)filtered*(long double)head.total/(long double)opened : 0;
        result<<id<<','<<(long double)filtered<<','<<ratio<<','<<(long double)head.total<<'\n';
    }
    return !result;
}

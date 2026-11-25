// Reuse the frozen implementations unchanged, allowing a different row budget per request.
#define main archived_benchmark_entry
#include "../multiway_joins/bench.cpp"
#undef main

int main(int argc,char** argv) {
    if(argc!=5) return 2;
    Store store(argv[1]);
    map<string,const Query*> queries;
    for(const auto& q:store.queries) queries.emplace(q.id,&q);
    const map<string,Policy> policies={{"certificate",Policy::Resume},{"natural",Policy::Natural},
                                      {"memo",Policy::Memo},{"indexed",Policy::KeyScan}};
    Run run(store,policies.at(argv[4]));
    ifstream schedule(argv[2]); ofstream result(argv[3]);
    result<<"case_id,budget,high,preflight_ns,shape_build,keys_opened\n";
    string id;
    while(schedule>>id>>Budget) {
        auto q=queries.at(id); auto start=Clock::now();
        bool fits=run.decide(*q);
        auto elapsed=chrono::duration_cast<chrono::nanoseconds>(Clock::now()-start).count();
        if(fits!=(q->truth<=Budget)) throw runtime_error("bad row decision");
        result<<id<<','<<Budget<<','<<!fits<<','<<elapsed<<','<<run.builds<<','<<run.opened<<'\n';
    }
    return !result;
}


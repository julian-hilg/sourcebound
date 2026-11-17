# Project pipelines

Only for data that is specific to this study. Data that other studies could use
(prices, benchmarks, geography, macro series) belongs in the hub (`sb which home`): `pipelines/<source>/`
with a contract in the registry (`sb which registry`), `contracts/<domain>/`.

One folder per source, following the hub's `pipelines/ecb_fx/`:

    pipelines/<source>/pipeline.py        fetch (sourcebound.fetch) -> parse -> lake.write
    pipelines/<source>/fixtures/          1-3 stored real responses
    pipelines/<source>/test_pipeline.py   parser tests, offline

Tables written from here use the schema `proj_<slug>` and a contract in the `contracts/` folder of
this project (`contracts/proj_<slug>/<table>.yaml`).

DROP TABLE IF EXISTS game CASCADE;

CREATE TABLE game (
    steam_app_id int,
    game_name text,

    CONSTRAINT game_pk PRIMARY KEY (steam_app_id)
);

DROP TABLE IF EXISTS game_crawl CASCADE;

CREATE TABLE game_crawl (
    steam_app_id int,
    crawl_time timestamp with time zone DEFAULT (now() at time zone 'utc'),
    game_name text,
    short_description text,
    reviews_last_30_days int,
    pct_positive_reviews_last_30_days real,
    reviews_all_time int,
    pct_positive_reviews_all_time real,
    release_date date,
    title text,
    genre text,
    developer text,
    publisher text,
    num_achievements int,
    full_price real,
    long_description text,

    CONSTRAINT game_crawl_pk PRIMARY KEY (steam_app_id, crawl_time),
    CONSTRAINT game_game_crawl_fk FOREIGN KEY (steam_app_id)
        REFERENCES game (steam_app_id)
);
DROP TABLE IF EXISTS steam_tag CASCADE;

CREATE TABLE steam_tag (
    tag_id serial,
    descr text,

    CONSTRAINT steam_tag_pk PRIMARY KEY (tag_id),
    CONSTRAINT steam_tag_descr_uniq UNIQUE (descr)
);

DROP TABLE IF EXISTS game_crawl_tag CASCADE;

CREATE TABLE game_crawl_tag (
    steam_app_id int,
    crawl_time timestamp with time zone,
    tag_id int,

    CONSTRAINT game_crawl_tag_pk PRIMARY KEY (steam_app_id, crawl_time, tag_id),
    CONSTRAINT game_crawl_game_crawl_tag_fk FOREIGN KEY (steam_app_id, crawl_time)
        REFERENCES game_crawl (steam_app_id, crawl_time),
    CONSTRAINT steam_tag_game_crawl_tag_fk FOREIGN KEY (tag_id)
        REFERENCES steam_tag (tag_id)
);

DROP TABLE IF EXISTS steam_game_detail CASCADE;

CREATE TABLE steam_game_detail (
     detail_id serial,
     descr text,

    CONSTRAINT steam_game_detail_pk PRIMARY KEY (detail_id),
    CONSTRAINT steam_game_detail_descr_uniq UNIQUE (descr)
);

DROP TABLE IF EXISTS game_crawl_detail CASCADE;

CREATE TABLE game_crawl_detail (
    steam_app_id int,
    crawl_time timestamp with time zone,
    detail_id int,

    CONSTRAINT game_crawl_detail_pk PRIMARY KEY (steam_app_id, crawl_time, detail_id),
    CONSTRAINT game_crawl_game_crawl_detail_fk FOREIGN KEY (steam_app_id, crawl_time)
        REFERENCES game_crawl (steam_app_id, crawl_time),
    CONSTRAINT steam_game_detail_game_crawl_detail_fk FOREIGN KEY (detail_id)
        REFERENCES steam_game_detail (detail_id)
);



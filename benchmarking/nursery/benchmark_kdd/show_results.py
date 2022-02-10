# %%
import logging
import os
from argparse import ArgumentParser

import dill
from sklearn.preprocessing import QuantileTransformer
from tqdm import tqdm

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime
from matplotlib import cm
import matplotlib.pyplot as plt
import numpy as np
from syne_tune.constants import ST_TUNER_TIME
from syne_tune.experiments import get_metadata, load_experiments_df

# %%
from syne_tune.util import catchtime

rs_color = "blue"
gp_color = "orange"
tpe_color = "red"
rea_color = "brown"
hb_bb_color = "green"
hb_ts_color = "yellow"
fifo_style = 'solid'
multifidelity_style = 'dashed'
multifidelity_style2 = 'dashdot'
transfer_style = 'dotted'


@dataclass
class MethodSyle:
    color: str
    linestyle: str
    marker: str = None


show_seeds = False
method_styles = {
    'RS': MethodSyle(rs_color, fifo_style),
    'GP': MethodSyle(gp_color, fifo_style),
    'REA': MethodSyle(rea_color, fifo_style),
    'HB': MethodSyle(rs_color, multifidelity_style),
    'RS-MSR': MethodSyle(rs_color, multifidelity_style2),
    'BOHB': MethodSyle(tpe_color, multifidelity_style),
    'MOBSTER': MethodSyle(gp_color, multifidelity_style),
    # transfer learning
    'HB-BB': MethodSyle(hb_bb_color, multifidelity_style, "."),
    'HB-CTS': MethodSyle(hb_ts_color, multifidelity_style, ".")
}


@dataclass
class PlotArgs:
    xmin: float = None
    xmax: float = None
    ymin: float = None
    ymax: float = None


plot_range = {
    "fcnet-naval": PlotArgs(50, None, 0.0, 4e-3),
    "fcnet-parkinsons": PlotArgs(0, None, 0.0, 0.1),
    "fcnet-protein": PlotArgs(xmin=0, ymin=0.225, ymax=0.35),
    "fcnet-slice": PlotArgs(50, None, 0.0, 0.004),
    "nas201-ImageNet16-120": PlotArgs(1000, None, None, 0.8),
    "nas201-cifar10": PlotArgs(2000, None, 0.05, 0.15),
    "nas201-cifar100": PlotArgs(3000, None, 0.26, 0.35),
}


def generate_df_dict(tag=None, date_min=None, date_max=None, methods_to_show=None) -> Dict[str, pd.DataFrame]:
    # todo load one df per task would be more efficient
    def metadata_filter(metadata, benchmark=None, tag=None):
        if methods_to_show is not None and not metadata['algorithm'] in methods_to_show:
            return False
        if benchmark is not None and metadata['benchmark'] != benchmark:
            return False
        if tag is not None and metadata['tag'] != tag:
            return False
        if date_min is None or date_max is None:
            return True
        else:
            date_exp = datetime.fromtimestamp(metadata['st_tuner_creation_timestamp'])
            return date_min <= date_exp <= date_max

    metadatas = get_metadata()
    if tag is not None:
        metadatas = {k: v for k, v in metadatas.items() if v.get("tag") == tag}
    # only select metadatas that contain the fields we are interested in
    metadatas = {
        k: v for k, v in metadatas.items()
        if all(key in v for key in ['algorithm', 'benchmark', 'tag', 'st_tuner_creation_timestamp'])
    }
    metadata_df = pd.DataFrame(metadatas.values())
    metadata_df['creation_date'] = metadata_df['st_tuner_creation_timestamp'].apply(lambda x: datetime.fromtimestamp(x))
    creation_dates_min_max = metadata_df.groupby(['algorithm']).agg(['min', 'max'])['creation_date']
    print("creation date per method:\n" + creation_dates_min_max.to_string())

    count_per_seed = metadata_df.groupby(['algorithm', 'benchmark', 'seed']).count()['tag'].unstack()
    print("num seeds per methods: \n" + count_per_seed.to_string())

    num_seed_per_method = metadata_df.groupby(['algorithm', 'benchmark']).count()['tag'].unstack()
    print("seeds present: \n" + num_seed_per_method.to_string())

    benchmarks = list(sorted(metadata_df.benchmark.dropna().unique()))

    benchmark_to_df = {}

    for benchmark in tqdm(benchmarks):
        valid_exps = set([name for name, metadata in metadatas.items() if metadata_filter(metadata, benchmark, tag)])
        if len(valid_exps) > 0:
            def name_filter(path):
                tuner_name = Path(path).parent.stem
                return tuner_name in valid_exps

            df = load_experiments_df(name_filter)
            benchmark_to_df[benchmark] = df

    return benchmark_to_df


def plot_result_benchmark(
        df_task,
        title: str,
        colors: Dict,
        show_seeds: bool = False,
        methods_to_show: Optional[List[str]] = None,
):
    agg_results = {}
    if len(df_task) > 0:
        metric = df_task.loc[:, 'metric_names'].values[0]
        mode = df_task.loc[:, 'metric_mode'].values[0]

        fig, ax = plt.subplots()
        if methods_to_show is None:
            methods_to_show = sorted(df_task.algorithm.unique())
        for algorithm in methods_to_show:
            ts = []
            ys = []

            df_scheduler = df_task[df_task.algorithm == algorithm]
            if len(df_scheduler) == 0:
                continue
            for i, tuner_name in enumerate(df_scheduler.tuner_name.unique()):
                sub_df = df_scheduler[df_scheduler.tuner_name == tuner_name]
                sub_df = sub_df.sort_values(ST_TUNER_TIME)
                t = sub_df.loc[:, ST_TUNER_TIME].values
                y_best = sub_df.loc[:, metric].cummax().values if mode == 'max' else sub_df.loc[:,
                                                                                     metric].cummin().values
                if show_seeds:
                    ax.plot(t, y_best, color=colors[algorithm], alpha=0.2)
                ts.append(t)
                ys.append(y_best)

            # compute the mean/std over time-series of different seeds at regular time-steps
            # start/stop at respectively first/last point available for all seeds
            t_min = max(tt[0] for tt in ts)
            t_max = min(tt[-1] for tt in ts)
            if t_min > t_max:
                continue
            t_range = np.linspace(t_min, t_max)

            # find the best value at each regularly spaced time-step from t_range
            y_ranges = []
            for t, y in zip(ts, ys):
                indices = np.searchsorted(t, t_range, side="left")
                y_range = y[indices]
                y_ranges.append(y_range)
            y_ranges = np.stack(y_ranges)

            mean = y_ranges.mean(axis=0)
            std = y_ranges.std(axis=0)
            ax.fill_between(
                t_range, mean - std, mean + std,
                color=colors[algorithm], alpha=0.1,
            )
            ax.plot(t_range, mean, color=colors[algorithm], label=algorithm)
            agg_results[algorithm] = mean

        ax.set_xlabel("wallclock time")
        ax.set_ylabel(metric)
        ax.legend()
        ax.set_title(title)
    return ax, t_range, agg_results


def plot_result_benchmark(
        df_task,
        title: str,
        show_seeds: bool = False,
        method_styles: Optional[Dict] = None,
):
    agg_results = {}
    if len(df_task) > 0:
        metric = df_task.loc[:, 'metric_names'].values[0]
        mode = df_task.loc[:, 'metric_mode'].values[0]

        fig, ax = plt.subplots()
        for algorithm, method_style in method_styles.items():
            ts = []
            ys = []

            df_scheduler = df_task[df_task.algorithm == algorithm]
            if len(df_scheduler) == 0:
                continue
            for i, tuner_name in enumerate(df_scheduler.tuner_name.unique()):
                sub_df = df_scheduler[df_scheduler.tuner_name == tuner_name]
                sub_df = sub_df.sort_values(ST_TUNER_TIME)
                t = sub_df.loc[:, ST_TUNER_TIME].values
                y_best = sub_df.loc[:, metric].cummax().values if mode == 'max' else sub_df.loc[:,
                                                                                     metric].cummin().values
                if show_seeds:
                    ax.plot(
                        t, y_best,
                        color=method_style.color,
                        linestyle=method_style.linestyle,
                        marker=method_style.marker,
                        alpha=0.2
                    )
                ts.append(t)
                ys.append(y_best)

            # compute the mean/std over time-series of different seeds at regular time-steps
            # start/stop at respectively first/last point available for all seeds
            t_min = max(tt[0] for tt in ts)
            t_max = min(tt[-1] for tt in ts)
            if t_min > t_max:
                continue
            t_range = np.linspace(t_min, t_max)

            # find the best value at each regularly spaced time-step from t_range
            y_ranges = []
            for t, y in zip(ts, ys):
                indices = np.searchsorted(t, t_range, side="left")
                y_range = y[indices]
                y_ranges.append(y_range)
            y_ranges = np.stack(y_ranges)

            mean = y_ranges.mean(axis=0)
            std = y_ranges.std(axis=0)
            ax.fill_between(
                t_range, mean - std, mean + std,
                color=method_style.color, alpha=0.1,
            )
            ax.plot(
                t_range, mean,
                color=method_style.color,
                linestyle=method_style.linestyle,
                marker=method_style.marker,
                label=algorithm,
            )
            agg_results[algorithm] = mean

        ax.set_xlabel("wallclock time")
        ax.set_ylabel(metric)
        ax.legend()
        ax.set_title(title)
    return ax, t_range, agg_results


def plot_results(benchmarks_to_df, method_styles: Optional[Dict] = None, prefix: str = ""):
    agg_results = {}

    for benchmark, df_task in benchmarks_to_df.items():
        ax, t_range, agg_result = plot_result_benchmark(
            df_task=df_task, title=benchmark, method_styles=method_styles, show_seeds=show_seeds
        )
        agg_results[benchmark] = agg_result
        if benchmark in plot_range:
            plotargs = plot_range[benchmark]
            ax.set_ylim([plotargs.ymin, plotargs.ymax])
            ax.set_xlim([plotargs.xmin, plotargs.xmax])

        plt.tight_layout()
        plt.savefig(f"figures/{prefix}{benchmark}.pdf")
        plt.show()


def print_rank_table(benchmarks_to_df, methods_to_show: Optional[List[str]] = None):
    def get_results(df_task):
        seed_results = {}
        if len(df_task) > 0:
            metric = df_task.loc[:, 'metric_names'].values[0]
            mode = df_task.loc[:, 'metric_mode'].values[0]

            for algorithm in sorted(df_task.algorithm.unique()):
                ts = []
                ys = []

                df_scheduler = df_task[df_task.algorithm == algorithm]
                for i, tuner_name in enumerate(df_scheduler.tuner_name.unique()):
                    sub_df = df_scheduler[df_scheduler.tuner_name == tuner_name]
                    sub_df = sub_df.sort_values(ST_TUNER_TIME)
                    t = sub_df.loc[:, ST_TUNER_TIME].values
                    y_best = sub_df.loc[:, metric].cummax().values if mode == 'max' else sub_df.loc[:,
                                                                                         metric].cummin().values
                    ts.append(t)
                    ys.append(y_best)

                # compute the mean/std over time-series of different seeds at regular time-steps
                # start/stop at respectively first/last point available for all seeds
                t_min = max(tt[0] for tt in ts)
                t_max = min(tt[-1] for tt in ts)
                if t_min > t_max:
                    continue
                t_range = np.linspace(t_min, t_max, 10)

                # find the best value at each regularly spaced time-step from t_range
                y_ranges = []
                for t, y in zip(ts, ys):
                    indices = np.searchsorted(t, t_range, side="left")
                    y_range = y[indices]
                    y_ranges.append(y_range)
                y_ranges = np.stack(y_ranges)

                seed_results[algorithm] = y_ranges

        # seed_results shape (num_seeds, num_time_steps)
        return t_range, seed_results

    benchmark_results = {}
    for benchmark, df_task in tqdm(list(benchmarks_to_df.items())):
        # (num_seeds, num_time_steps)
        _, seed_results_dict = get_results(df_task)

        shapes = [x.shape for x in seed_results_dict.values()]

        # take the minimum number of seeds in case some are missing
        min_num_seeds = min(num_seed for num_seed, num_time_steps in shapes)

        # (num_methods, num_min_seeds, num_time_steps)
        seed_results = np.stack([x[:min_num_seeds] for x in seed_results_dict.values()])

        num_methods = len(seed_results)
        seed_results = seed_results.reshape(num_methods, -1)

        # (num_methods, num_min_seeds, num_time_steps)
        ranks = QuantileTransformer().fit_transform(seed_results)
        ranks = ranks.reshape(num_methods, min_num_seeds, -1)

        # (num_methods, num_min_seeds)
        benchmark_results[benchmark] = ranks.mean(axis=-1)

    # take the minimum number of seeds in case some are missing
    min_num_seeds = min(x.shape[1] for x in benchmark_results.values())

    # (num_bench, num_methods, num_min_seeds)
    ranks = np.stack([x[:, :min_num_seeds] for x in benchmark_results.values()])

    methods = sorted(df_task.algorithm.unique())

    df_ranks = pd.Series(ranks.mean(axis=-1).mean(axis=0), index=methods)
    df_ranks_std = ranks.std(axis=-1).mean(axis=0)
    df_ranks = df_ranks[[
        'RS',
        'REA',
        'GP',
        'RS-MSR',
        'BOHB',
        'HB',
        'MOBSTER',
        'HB-BB',
        'HB-CTS',
    ]]

    print(df_ranks.to_string())
    print(df_ranks.to_latex(float_format="%.2f"))


def load_and_cache(experiment_tag: str, load_cache_if_exists: bool = True, methods_to_show=None):

    result_file = Path(f"~/Downloads/cached-results-{experiment_tag}.dill").expanduser()
    if load_cache_if_exists and result_file.exists():
        with catchtime(f"loading results from {result_file}"):
            with open(result_file, "rb") as f:
                benchmarks_to_df = dill.load(f)
    else:
        print(f"regenerating results to {result_file}")
        benchmarks_to_df = generate_df_dict(experiment_tag, date_min=None, date_max=None, methods_to_show=methods_to_show)
        # metrics = df.metric_names
        with open(result_file, "wb") as f:
            dill.dump(benchmarks_to_df, f)

    return benchmarks_to_df


if __name__ == '__main__':
    date_min = datetime.fromisoformat("2022-01-04")
    date_max = datetime.fromisoformat("2023-01-04")

    parser = ArgumentParser()
    parser.add_argument(
        "--experiment_tag", type=str, required=False, default="mahogany-snake",
        help="the experiment tag that was displayed when running the experiment"
    )
    args, _ = parser.parse_known_args()
    experiment_tag = args.experiment_tag
    logging.getLogger().setLevel(logging.INFO)

    load_cache_if_exists = True

    # benchmarks_to_df = {bench: df[] for bench, df in benchmarks_to_df.items()}
    methods_to_show = list(method_styles.keys())
    benchmarks_to_df = load_and_cache(load_cache_if_exists=load_cache_if_exists, experiment_tag=experiment_tag, methods_to_show=methods_to_show)
    for bench, df_ in benchmarks_to_df.items():
        df_methods = df_.algorithm.unique()
        for x in methods_to_show:
            if x not in df_methods:
                logging.warning(f"method {x} not found in {bench}")

    # plot_results(benchmarks_to_df, method_styles)

    print_rank_table(benchmarks_to_df, methods_to_show)
